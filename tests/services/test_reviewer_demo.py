from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request


def settings():
    return SimpleNamespace(REVIEWER_DEMO_MODE=True, AUTH_COOKIE_NAME="auth",
        DEMO_AI_DAILY_LIMIT=20, DEMO_AI_GLOBAL_DAILY_LIMIT=100)


@pytest.mark.asyncio
async def test_anonymous_write_is_denied_before_body_or_provider(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value=None))
    downstream = AsyncMock()
    receive = AsyncMock(side_effect=AssertionError("body must not be read"))
    send = AsyncMock()
    await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
        {"type":"http", "method":"POST", "path":"/chat", "headers":[], "client":("peer",1)}, receive, send)
    assert send.await_args_list[0].args[0]["status"] == 401
    downstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_user_quota_failure_is_closed(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value={"_id":"u", "email_verified":True, "status":"active"}))
    monkeypatch.setattr(demo, "reserve_demo_budget", AsyncMock(side_effect=RuntimeError("database")))
    downstream, send = AsyncMock(), AsyncMock()
    await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
        {"type":"http", "method":"POST", "path":"/chat", "headers":[], "client":("peer",1)}, AsyncMock(), send)
    assert send.await_args_list[0].args[0]["status"] == 503
    downstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_read_does_not_require_login(monkeypatch):
    import app.services.reviewer_demo as demo
    resolve = AsyncMock(side_effect=AssertionError("no login"))
    monkeypatch.setattr(demo, "resolve_auth_session", resolve)
    downstream = AsyncMock()
    await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
        {"type":"http", "method":"GET", "path":"/evaluation-lab", "headers":[]}, AsyncMock(), AsyncMock())
    downstream.assert_awaited_once()


def test_public_rate_limit_is_not_reset_by_cookie():
    from app.services.web_security import public_rate_limit_key
    a = Request({"type":"http", "headers":[], "client":("peer",1), "state":{"client_id":"a"}})
    b = Request({"type":"http", "headers":[], "client":("peer",1), "state":{"client_id":"b"}})
    assert public_rate_limit_key(a) == public_rate_limit_key(b)


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, {"_id":"u", "email_verified":False}, {"_id":"u", "email_verified":True, "status":"disabled"}])
async def test_all_mutations_require_verified_active_account(monkeypatch, user):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value=user))
    for path in ["/chat/", "/workspaces/w/documents", "/workspaces/w/research/run", "/api/evaluation/t", "/sessions", "/workspaces/w/analyses/compare"]:
        downstream, send = AsyncMock(), AsyncMock()
        await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
            {"type":"http", "method":"POST", "path":path, "headers":[]}, AsyncMock(), send)
        assert send.await_args_list[0].args[0]["status"] == 401
        downstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticated_request_preserves_body_and_reserves_ai_budget(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value={"_id":"u", "email_verified":True}))
    reserve = AsyncMock(return_value=True)
    monkeypatch.setattr(demo, "reserve_demo_budget", reserve)
    received = []
    async def downstream(scope, receive, send):
        received.append(await receive())
    message = {"type":"http.request", "body":b"csrf_token=x&message=test", "more_body":False}
    await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
        {"type":"http", "method":"POST", "path":"/chat", "headers":[]}, AsyncMock(return_value=message), AsyncMock())
    assert received == [message]
    assert reserve.await_args_list[0].args == ("u", "ai", 3, 60)
    assert reserve.await_args_list[1].args == ("u", "ai", 20, 100)


@pytest.mark.asyncio
async def test_oversized_stream_and_quota_exhaustion_never_reach_handler(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value={"_id":"u", "email_verified":True}))
    for allowed, expected in [(True,413), (False,429)]:
        monkeypatch.setattr(demo, "reserve_demo_budget", AsyncMock(return_value=allowed))
        downstream, send = AsyncMock(), AsyncMock()
        receive = AsyncMock(return_value={"type":"http.request", "body":b"x" * 65537, "more_body":False})
        await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
            {"type":"http", "method":"POST", "path":"/chat", "headers":[]}, receive, send)
        assert send.await_args_list[0].args[0]["status"] == expected
        downstream.assert_not_awaited()
        if not allowed:
            receive.assert_not_awaited()


@pytest.mark.asyncio
async def test_budget_uses_atomic_subject_and_global_guard_and_hashes_identity(monkeypatch):
    import app.services.reviewer_demo as demo
    from pymongo.errors import DuplicateKeyError
    collection = SimpleNamespace(insert_one=AsyncMock(side_effect=DuplicateKeyError("existing")),
                                 update_one=AsyncMock(return_value=SimpleNamespace(modified_count=0)))
    monkeypatch.setattr(demo, "get_db", lambda: SimpleNamespace(demo_usage=collection))
    assert not await demo.reserve_demo_budget("private-subject", "ai", 20, 100)
    query, update = collection.update_one.await_args.args
    assert query["count"] == {"$lt":100}
    assert query["$expr"]["$lt"][1] == 20
    assert update["$inc"]["count"] == 1
    assert "private-subject" not in str(collection.insert_one.await_args) + str(query) + str(update)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/logout", "/account/sessions/s/revoke", "/account/sessions/revoke-others", "/account/history/delete", "/account/delete"])
async def test_security_and_privacy_actions_survive_exhausted_write_quota(monkeypatch, path):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, "resolve_auth_session", AsyncMock(return_value={"_id":"u", "email_verified":True}))
    reserve = AsyncMock(return_value=False)
    monkeypatch.setattr(demo, "reserve_demo_budget", reserve)
    downstream = AsyncMock()
    await demo.ReviewerDemoMiddleware(downstream, settings=settings())(
        {"type":"http", "method":"POST", "path":path, "headers":[]},
        AsyncMock(return_value={"type":"http.request", "body":b"csrf_token=test", "more_body":False}), AsyncMock())
    downstream.assert_awaited_once()
    reserve.assert_not_awaited()

@pytest.mark.asyncio
async def test_quota_snapshot_projects_only_current_subject_and_global(monkeypatch):
    import hashlib
    import app.services.reviewer_demo as demo
    digest = hashlib.sha256(b'user-a').hexdigest()
    collection = SimpleNamespace(find_one=AsyncMock(return_value={'count': 99, 'subjects': {digest: 7}}))
    monkeypatch.setattr(demo, 'get_db', lambda: SimpleNamespace(demo_usage=collection))
    result = await demo.get_demo_quota('user-a', settings())
    assert result['status'] == 'ok'
    assert result['ai']['used'] == 7
    assert result['ai']['remaining'] == 13
    assert result['ai']['available'] == 1
    assert 'subjects' not in str(result)
    assert collection.find_one.await_args_list[0].args[1] == {'count': 1, 'subjects.' + digest: 1}

@pytest.mark.asyncio
async def test_quota_snapshot_failure_never_claims_unused_budget(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, 'get_db', lambda: SimpleNamespace(demo_usage=SimpleNamespace(find_one=AsyncMock(side_effect=RuntimeError('private db error')))))
    assert await demo.get_demo_quota('u', settings()) == {'status': 'unavailable'}

@pytest.mark.asyncio
async def test_disabled_quota_does_not_access_database(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, 'get_db', lambda: pytest.fail('database should not be read'))
    config = settings()
    config.REVIEWER_DEMO_MODE = False
    assert await demo.get_demo_quota('u', config) == {'status': 'disabled'}

@pytest.mark.asyncio
async def test_denial_counters_are_bounded_and_contain_no_subject(monkeypatch):
    import app.services.reviewer_demo as demo
    monkeypatch.setattr(demo, 'resolve_auth_session', AsyncMock(return_value=None))
    before = demo.demo_admission_snapshot()['denied'].get('demo_login_required', 0)
    await demo.ReviewerDemoMiddleware(AsyncMock(), settings=settings())(
        {'type':'http', 'method':'POST', 'path':'/chat', 'headers':[], 'client':('private-peer',1)}, AsyncMock(), AsyncMock())
    snapshot = demo.demo_admission_snapshot()
    assert snapshot['denied']['demo_login_required'] == before + 1
    assert snapshot['scope'] == 'process_since_start'
    assert 'private-peer' not in str(snapshot)
