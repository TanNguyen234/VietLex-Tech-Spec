"""Demo admission before body parsing; durable attempt quotas, no provider calls."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import re

from pymongo.errors import DuplicateKeyError
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from app.account_database import resolve_auth_session
from app.database import get_db

_AUTH = {'/login', '/register', '/forgot-password', '/reset-password', '/verify-email'}
_PROTECTIVE = re.compile(r'^/(?:logout|account/(?:delete|history/delete|sessions/(?:revoke-others|[^/]+/revoke)))$')
_UPLOAD = re.compile(r'^/workspaces/[^/]+/documents$')
_AI = re.compile(r'^/workspaces/[^/]+/(?:analyses/[^/]+|research/run|documents/[^/]+/review)$')


async def reserve_demo_budget(subject: str, category: str, personal: int, total: int,
                              *, minute: bool = False) -> bool:
    """One bounded document per category/window; atomic global and subject caps.

    Reservations are attempts, including downstream failures. No refunds or raw
    IP/user identifiers; later quota failures conservatively retain earlier slots.
    """
    now = datetime.now(timezone.utc)
    window = now.strftime('%Y-%m-%dT%H:%M' if minute else '%Y-%m-%d')
    key = category + ':' + window
    field = 'subjects.' + hashlib.sha256(subject.encode()).hexdigest()
    collection = get_db().demo_usage
    try:
        await collection.insert_one({'_id': key, 'count': 0, 'subjects': {},
                                     'expires_at': now + timedelta(days=2)})
    except DuplicateKeyError:
        pass
    result = await collection.update_one(
        {'_id': key, 'count': {'$lt': total},
         '$expr': {'$lt': [{'$ifNull': ['$' + field, 0]}, personal]}},
        {'$inc': {'count': 1, field: 1}},
    )
    return result.modified_count == 1


class ReviewerDemoMiddleware:
    def __init__(self, app, *, settings):
        self.app, self.settings = app, settings
        self.active_bodies = 0

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not self.settings.REVIEWER_DEMO_MODE:
            await self.app(scope, receive, send)
            return
        path = scope.get('path', '').rstrip('/') or '/'
        mutation = scope.get('method') not in {'GET', 'HEAD', 'OPTIONS'}
        if not mutation and path != '/verify-email':
            await self.app(scope, receive, send)
            return
        request = Request(scope)

        async def deny(status, kind, message):
            headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
            if status == 429:
                headers['Retry-After'] = '60' if kind == 'demo_minute_quota' else '86400'
            if request.headers.get('hx-request') or 'text/html' in request.headers.get('accept', ''):
                response = HTMLResponse('<div role="alert">' + message +
                    ' <a href="/account">Tài khoản</a></div>', status_code=status, headers=headers)
            else:
                response = JSONResponse({'detail': kind, 'message': message}, status_code=status, headers=headers)
            await response(scope, receive, send)

        try:
            if path in _AUTH:
                subject = str((scope.get('client') or ('unknown',))[0])
                category, personal, total = 'auth', 15, 200
                per_minute = 5
            else:
                user = await asyncio.wait_for(resolve_auth_session(
                    request.cookies.get(self.settings.AUTH_COOKIE_NAME)), timeout=3)
                if not user or user.get('status', 'active') != 'active' or not user.get('email_verified'):
                    await deny(401, 'demo_login_required', 'Đăng nhập tài khoản đã xác minh để dùng chức năng này.')
                    return
                subject = str(user['_id'])
                expensive = path == '/chat' or path.startswith('/api/evaluation/') or bool(_AI.fullmatch(path))
                category = 'ai' if expensive else 'write'
                personal = self.settings.DEMO_AI_DAILY_LIMIT if expensive else 100
                total = self.settings.DEMO_AI_GLOBAL_DAILY_LIMIT if expensive else 1000
                per_minute = 3 if expensive else 15
            # Shared work quota must never lock users out of privacy/session controls.
            budgets = [] if _PROTECTIVE.fullmatch(path) else [(True, per_minute, 60), (False, personal, total)]
            for minute, own, global_cap in budgets:
                allowed = await asyncio.wait_for(reserve_demo_budget(
                    subject, category, own, global_cap, minute=minute), timeout=3)
                if not allowed:
                    await deny(429, 'demo_minute_quota' if minute else 'demo_daily_quota',
                               'Đã hết lượt dùng trong phút này.' if minute else 'Đã hết quota demo hôm nay (UTC).')
                    return
        except Exception:
            await deny(503, 'demo_admission_unavailable', 'Tạm dừng thao tác vì chưa kiểm tra được quyền/quota. Vui lòng thử lại sau.')
            return

        # Auth and quota checks precede multipart spooling and all provider work.
        if mutation:
            if self.active_bodies >= 2:
                await deny(503, 'demo_capacity_limit', 'Demo đang bận. Vui lòng thử lại sau.')
                return
            self.active_bodies += 1
            try:
                cap = 4_000_000 if _UPLOAD.fullmatch(path) else 65_536
                messages, observed = [], 0
                try:
                    async with asyncio.timeout(15):
                        while True:
                            message = await receive()
                            if message['type'] == 'http.disconnect':
                                return
                            observed += len(message.get('body', b''))
                            if observed > cap:
                                await deny(413, 'demo_body_too_large', 'Dữ liệu vượt giới hạn bản demo (upload dưới 4 MB).')
                                return
                            messages.append(message)
                            if not message.get('more_body', False):
                                break
                except TimeoutError:
                    await deny(408, 'demo_body_timeout', 'Hết thời gian nhận dữ liệu.')
                    return
    
                async def replay():
                    return messages.pop(0) if messages else await receive()
    
                await self.app(scope, replay, send)
            finally:
                self.active_bodies -= 1

        else:
            await self.app(scope, receive, send)
