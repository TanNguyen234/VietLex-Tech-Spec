from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_admin, verify_csrf
from app.api.routes import _sanitize_admin_interaction, router
from app.rate_limit import limiter


def _client():
    limiter._storage.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[require_admin] = lambda: {
        "_id": "admin-1", "role": "admin", "status": "active"
    }
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.include_router(router)
    return TestClient(app)


def test_admin_disable_creates_audit_record(monkeypatch) -> None:
    import app.api.routes as routes

    set_status = AsyncMock(return_value=True)
    audit = AsyncMock()
    monkeypatch.setattr(routes, "set_user_status", set_status)
    monkeypatch.setattr(routes, "write_admin_audit", audit)

    response = _client().post(
        "/admin/users/user-1/status",
        data={"account_status": "disabled", "csrf_token": "valid"},
        headers={"x-request-id": "request-1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    set_status.assert_awaited_once_with("user-1", "disabled")
    assert audit.await_args.args[:4] == (
        "admin-1", "account_disabled", "user", "user-1"
    )


def test_admin_cannot_disable_self(monkeypatch) -> None:
    import app.api.routes as routes

    set_status = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "set_user_status", set_status)

    response = _client().post(
        "/admin/users/admin-1/status",
        data={"account_status": "disabled", "csrf_token": "valid"},
    )

    assert response.status_code == 409
    set_status.assert_not_awaited()


def test_admin_revoke_sessions_rejects_unknown_user(monkeypatch) -> None:
    import app.api.routes as routes

    monkeypatch.setattr(routes, "get_user_by_id", AsyncMock(return_value=None))
    revoke = AsyncMock()
    monkeypatch.setattr(routes, "revoke_all_auth_sessions", revoke)

    response = _client().post(
        "/admin/users/missing/revoke-sessions",
        data={"csrf_token": "valid"},
    )

    assert response.status_code == 404
    revoke.assert_not_awaited()


def test_admin_interaction_display_is_redacted_and_bounded() -> None:
    result = _sanitize_admin_interaction({
        "user_query": "a" * 3_000,
        "bot_response": "b" * 12_000,
        "contexts": ["c" * 5_000] * 12,
    })

    assert len(result["user_query"]) <= 2_000
    assert len(result["bot_response"]) <= 10_000
    assert len(result["contexts"]) == 10
    assert all(len(context) <= 4_000 for context in result["contexts"])
def test_request_detail_shows_usage_context_and_eval_without_running_judge(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, 'get_interaction', AsyncMock(return_value={
        'trace_id': 'detail', 'user_query': '<script>alert(1)</script>',
        'bot_response': 'Answer', 'contexts': ['[Điều 25 · 45/2019/QH14]\n' + 'Evidence ' * 100],
        'metrics': {'llm_calls': [{'provider': 'vertex', 'model': 'model', 'total_token_count': 123}], 'ragas_status': 'disabled'},
    }))
    response = _client().get('/admin/details/detail')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert '<script>alert(1)</script>' not in response.text
    assert '&lt;script&gt;' in response.text
    for text in ('123', 'UNKNOWN', 'disabled', 'SHA-256', 'Evidence ' * 50):
        assert text in response.text


def test_admin_filters_are_validated_and_forwarded(monkeypatch):
    import app.api.routes as routes

    logs = AsyncMock(return_value=[])
    monkeypatch.setattr(routes, 'get_admin_logs', logs)
    client = _client()
    response = client.get('/admin/logs?start_date=2026-09-01&end_date=2026-09-05&model=gemini&ragas_status=disabled')
    assert response.status_code == 200
    assert logs.await_args.kwargs['model'] == 'gemini'
    assert logs.await_args.kwargs['start_date'].isoformat() == '2026-09-01'
    assert client.get('/admin/logs?start_date=2026-09-06&end_date=2026-09-01').status_code == 422
    assert client.get('/admin/logs?skip=-1').status_code == 422


def test_admin_export_redacts_and_neutralizes_csv_formulas(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, 'get_admin_logs', AsyncMock(return_value=[{
        'trace_id': 'export', 'user_query': '=HYPERLINK("evil") Bearer secret-token', 'contexts': [],
    }]))
    audit = AsyncMock()
    monkeypatch.setattr(routes, 'write_admin_audit', audit)
    response = _client().get('/admin/export.csv')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'secret-token' not in response.text
    assert "'=HYPERLINK" in response.text
    assert audit.await_count == 1
def test_admin_database_failure_is_not_empty_success(monkeypatch):
    import app.api.routes as routes
    from app.services.admin_observability import AdminDataUnavailable

    monkeypatch.setattr(routes, 'get_admin_logs', AsyncMock(side_effect=AdminDataUnavailable('db')))
    response = _client().get('/admin/logs')
    assert response.status_code == 503


def test_blank_date_and_cache_filters_are_accepted(monkeypatch):
    import app.api.routes as routes

    monkeypatch.setattr(routes, 'get_admin_logs', AsyncMock(return_value=[]))
    assert _client().get('/admin/logs?start_date=&end_date=&cache_hit=').status_code == 200
def test_admin_main_renders_filtered_stats_and_inventory(monkeypatch):
    import app.api.routes as routes

    stats = AsyncMock(return_value={'total_queries': 0, 'avg_faithfulness': None, 'avg_relevance': None})
    monkeypatch.setattr(routes, 'get_admin_stats', stats)
    monkeypatch.setattr(routes, 'get_admin_logs', AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, 'get_admin_inventory', AsyncMock(return_value={'status': 'unavailable', 'error_kind': 'test'}))
    monkeypatch.setattr(routes, 'list_users', AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, 'get_admin_audit_logs', AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, 'build_readiness', AsyncMock(return_value={'runtime': {'retrieval_backend': 'test'}, 'checks': {}}))
    response = _client().get('/admin?model=model')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert stats.await_args.kwargs['filters']['model'] == 'model'
    for text in ('Token', 'Độ đầy đủ', 'Tài khoản và dữ liệu', 'Xuất CSV'):
        assert text in response.text
def test_non_admin_cannot_read_requests_or_export(monkeypatch):
    import app.api.dependencies as dependencies
    import app.api.routes as routes

    client = _client()
    del client.app.dependency_overrides[require_admin]
    monkeypatch.setattr(dependencies, 'resolve_auth_session', AsyncMock(return_value={'_id': 'user', 'role': 'user', 'status': 'active'}))
    reader = AsyncMock()
    monkeypatch.setattr(routes, 'get_admin_logs', reader)
    for url in ('/admin', '/admin/stats', '/admin/logs', '/admin/details/id', '/admin/export.csv'):
        assert client.get(url).status_code == 403
    reader.assert_not_awaited()
def test_unavailable_stats_partial_does_not_render_zero_cards(monkeypatch):
    import app.api.routes as routes
    monkeypatch.setattr(routes, 'get_admin_stats', AsyncMock(return_value={'status':'unavailable','total_queries':0,'technical_error_count':0,'error_kind':'timeout'}))
    response = _client().get('/admin/stats')
    assert response.status_code == 503
    assert 'Không đọc được thống kê' in response.text
    assert 'admin-card' not in response.text
