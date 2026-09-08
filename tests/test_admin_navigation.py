from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import require_admin
from app.api.routes import router
from app.rate_limit import limiter


@pytest.fixture
def admin_pages(monkeypatch):
    import app.api.routes as routes
    limiter._storage.reset()
    readers = {}
    values = {
        "get_admin_stats": {"status": "available", "total_queries": 3, "technical_error_count": 1,
                            "daily": [{"_id": "2026-09-08", "requests": 3}],
                            "avg_faithfulness": None, "avg_relevance": None},
        "get_admin_logs": [], "get_admin_inventory": {"status": "unavailable", "error_kind": "test"},
        "list_users": [], "get_admin_audit_logs": [],
        "build_readiness": {"status": "ready", "runtime": {"retrieval_backend": "test"}, "checks": {}},
    }
    for name, value in values.items():
        readers[name] = AsyncMock(return_value=value)
        monkeypatch.setattr(routes, name, readers[name])
    app = FastAPI()
    app.state.limiter = limiter
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin-test", "role": "admin"}
    app.include_router(router)
    return TestClient(app), readers


@pytest.mark.parametrize("path, reader", [
    ("/admin/requests", "get_admin_logs"), ("/admin/usage", "get_admin_stats"),
    ("/admin/users", "list_users"), ("/admin/audit", "get_admin_audit_logs"),
    ("/admin/providers", None), ("/admin/system", "build_readiness"),
])
def test_admin_pages_are_separate_and_read_only_their_data(admin_pages, path, reader):
    client, readers = admin_pages
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'aria-label="Điều hướng quản trị"' in response.text
    assert f'href="{path}" aria-current="page"' in response.text
    for name, mock in readers.items():
        if name == reader:
            mock.assert_awaited_once()
        else:
            mock.assert_not_awaited()


def test_requests_filter_stays_on_requests_page(admin_pages):
    client, readers = admin_pages
    response = client.get("/admin/requests?model=example&skip=25")
    assert response.status_code == 200
    assert 'action="/admin/requests"' in response.text
    assert readers["get_admin_logs"].await_args.kwargs["model"] == "example"
    assert "/admin/requests?model=example&amp;skip=0" in response.text
    assert 'href="/admin/export.csv?model=example&amp;skip=25"' in response.text


@pytest.mark.parametrize("query", ["skip=-1", "limit=1000", "role=root", "account_status=deleted"])
def test_accounts_reject_invalid_filters_before_read(admin_pages, query):
    client, readers = admin_pages
    assert client.get("/admin/users?" + query).status_code == 422
    readers["list_users"].assert_not_awaited()


def test_dashboard_is_a_summary_not_all_management_forms(admin_pages):
    client, readers = admin_pages
    response = client.get("/admin")
    assert response.status_code == 200
    assert 'aria-label="Lưu lượng request theo ngày"' in response.text
    assert "2026-09-08" in response.text
    assert 'action="/admin/users' not in response.text
    readers["list_users"].assert_not_awaited()
    readers["get_admin_audit_logs"].assert_not_awaited()
    readers["build_readiness"].assert_not_awaited()


def test_accounts_page_issues_and_reuses_csrf_cookie(admin_pages):
    client, _ = admin_pages
    first = client.get("/admin/users")
    token = client.cookies.get("csrf_token")
    assert token
    assert "HttpOnly" in first.headers["set-cookie"]
    client.get("/admin/users")
    assert client.cookies.get("csrf_token") == token


@pytest.mark.parametrize("path", ["/admin/requests", "/admin/usage", "/admin/users", "/admin/audit", "/admin/providers", "/admin/system"])
def test_all_admin_pages_require_admin_before_read(admin_pages, monkeypatch, path):
    import app.api.dependencies as dependencies
    client, readers = admin_pages
    del client.app.dependency_overrides[require_admin]
    monkeypatch.setattr(dependencies, "resolve_auth_session", AsyncMock(return_value={"_id": "normal", "role": "user", "status": "active"}))
    assert client.get(path).status_code == 403
    for reader in readers.values():
        reader.assert_not_awaited()


def test_audit_pagination_and_errors_are_explicit(admin_pages):
    from app.services.admin_observability import AdminDataUnavailable
    client, readers = admin_pages
    response = client.get('/admin/audit?skip=50&limit=25')
    assert response.status_code == 200
    assert readers['get_admin_audit_logs'].await_args.kwargs['skip'] == 50
    assert readers['get_admin_audit_logs'].await_args.kwargs['strict'] is True
    assert client.get('/admin/audit?skip=-1').status_code == 422
    readers['get_admin_audit_logs'].side_effect = AdminDataUnavailable('database_unavailable')
    response = client.get('/admin/audit')
    assert response.status_code == 503
    assert 'aria-label="Điều hướng quản trị"' in response.text
    assert 'Chưa có audit log' not in response.text


def test_guardrail_failure_detail_does_not_show_success_defaults(admin_pages, monkeypatch):
    import app.api.routes as routes
    client, _ = admin_pages
    monkeypatch.setattr(routes, 'get_interaction', AsyncMock(return_value={
        'trace_id': 'guardrail-test', 'user_query': 'synthetic', 'contexts': [],
        'request_metadata': {'nemo_requested': True},
        'safety_status': {'input_safe': True, 'output_safe': True},
        'metrics': {'request_status': 'technical_error', 'technical_error': {
            'stage': 'guardrails_input', 'error_type': 'GuardrailUnavailableError'}},
    }))
    response = client.get('/admin/details/guardrail-test')
    assert response.status_code == 200
    assert 'aria-label="Điều hướng quản trị"' in response.text
    assert 'Guardrail không hoàn tất' in response.text
    assert 'Input: True' not in response.text


@pytest.mark.asyncio
async def test_strict_audit_reader_does_not_hide_database_failure(monkeypatch):
    import app.database as database
    from app.services.admin_observability import AdminDataUnavailable
    def unavailable():
        raise RuntimeError('synthetic database outage')
    monkeypatch.setattr(database, 'get_db', unavailable)
    with pytest.raises(AdminDataUnavailable):
        await database.get_admin_audit_logs(skip=0, limit=25, strict=True)
