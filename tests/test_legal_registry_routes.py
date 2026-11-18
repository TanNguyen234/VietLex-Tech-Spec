from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies import require_admin, optional_user


@pytest.fixture
def client(monkeypatch):
    import app.database as db_mod
    from app.api.legal_registry_routes import router

    monkeypatch.setattr(db_mod, "db", None)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = lambda: {"_id": "admin"}
    app.dependency_overrides[optional_user] = lambda: {"_id": "admin"}
    return TestClient(app)


def test_public_lookup_is_unknown_without_reviewed_events(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.legal_registry_routes.registry_records", AsyncMock(return_value=[])
    )
    response = client.get("/legal-status?document_number=A/2020&as_of=2023-01-01")
    assert response.status_code == 200
    assert "Chưa xác định" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_finite_registry_view_explains_inclusive_end_date(client, monkeypatch):
    from tests.services.test_legal_effect import _finite_review_data
    from app.services.legal_effect import review_legal_effect
    from app.services.legal_registry import publication_record
    evidence, event = _finite_review_data()
    analysis = dict(analysis_id='finite', kind='legal_effect_review', reviewer_id='human',
                    reviewed_at='2026-10-30T00:00:00+00:00', evidence_snapshot=evidence,
                    **review_legal_effect(evidence, '2026-10-30', [event]))
    record = publication_record(analysis, 'human')
    monkeypatch.setattr('app.api.legal_registry_routes.registry_records', AsyncMock(return_value=[record]))
    response = client.get('/legal-status?document_number=A/2026&as_of=2027-03-01')
    assert response.status_code == 200
    assert 'Đã qua ngày cuối hiệu lực' in response.text
    assert '2027-02-28' in response.text and 'bao gồm ngày này' in response.text
    assert 'chưa bao phủ đầy đủ' in response.text


def test_lookup_database_failure_does_not_look_like_no_events(client, monkeypatch):
    from app.legal_registry_database import RegistryUnavailable

    monkeypatch.setattr(
        "app.api.legal_registry_routes.registry_records",
        AsyncMock(side_effect=RegistryUnavailable()),
    )
    response = client.get("/legal-status?document_number=A/2020")
    assert response.status_code == 503
    assert "Không kết nối" in response.text


def test_invalid_date_rejected_before_database(client, monkeypatch):
    read = AsyncMock()
    monkeypatch.setattr("app.api.legal_registry_routes.registry_records", read)
    assert (
        client.get("/legal-status?document_number=A/2020&as_of=bad").status_code == 422
    )
    read.assert_not_awaited()


def test_publication_requires_csrf(client, monkeypatch):
    write = AsyncMock()
    monkeypatch.setattr("app.api.legal_registry_routes.publish_review", write)
    assert (
        client.post(
            "/workspaces/w-1/analyses/review-1/publish-legal-effect",
            data={"confirmed": "yes", "csrf_token": "forged"},
        ).status_code
        == 403
    )
    write.assert_not_awaited()


def test_publication_requires_explicit_confirmation(client, monkeypatch):
    from app.api.dependencies import verify_csrf

    client.app.dependency_overrides[verify_csrf] = lambda: "ok"
    write = AsyncMock()
    monkeypatch.setattr("app.api.legal_registry_routes.publish_review", write)
    assert (
        client.post(
            "/workspaces/w-1/analyses/review-1/publish-legal-effect",
            data={"confirmed": "no"},
        ).status_code
        == 422
    )
    write.assert_not_awaited()


def test_publication_rechecks_owned_review_and_only_then_writes(client, monkeypatch):
    from app.api.dependencies import verify_csrf
    from tests.services.test_legal_registry import review

    client.app.dependency_overrides[verify_csrf] = lambda: "ok"
    owned = AsyncMock(return_value=({"analyses": [review()]}, "client", "admin"))
    monkeypatch.setattr("app.api.legal_registry_routes._owned_workspace", owned)
    write = AsyncMock()
    monkeypatch.setattr("app.api.legal_registry_routes.publish_review", write)
    response = client.post(
        "/workspaces/w-1/analyses/review-1/publish-legal-effect",
        data={"confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    owned.assert_awaited_once()
    record = write.await_args.args[0]
    assert record["published_by"] == "admin"
    assert "private-evidence" not in str(record)


def test_withdrawal_requires_csrf_and_reports_stale_review(client, monkeypatch):
    from app.api.dependencies import verify_csrf

    withdraw = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.legal_registry_routes.withdraw_review", withdraw)
    path = "/admin/legal-registry/review-1/withdraw"
    data = {"reason": "Sai trích dẫn", "csrf_token": "forged"}

    rejected = client.post(path, data=data, follow_redirects=False)
    assert rejected.status_code == 403
    withdraw.assert_not_awaited()

    client.app.dependency_overrides[verify_csrf] = lambda: "valid"
    accepted = client.post(path, data=data, follow_redirects=False)
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/admin/legal-registry"
    withdraw.assert_awaited_once_with("review-1", "admin", "Sai trích dẫn")

    withdraw.return_value = False
    stale = client.post(path, data=data, follow_redirects=False)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "review_not_published_reload"


def test_registry_admin_requires_admin_role(client, monkeypatch):
    del client.app.dependency_overrides[require_admin]
    monkeypatch.setattr(
        "app.api.dependencies.resolve_auth_session",
        AsyncMock(return_value={"_id": "user", "role": "user", "status": "active"}),
    )
    assert client.get("/admin/legal-registry").status_code == 403


def test_admin_page_escapes_reviewed_quote(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.legal_registry_routes.registry_records",
        AsyncMock(
            return_value=[
                {
                    "_id": "review-1",
                    "state": "published",
                    "published_at": "today",
                    "assertions": [
                        {
                            "exact_quote": "<script>alert(1)</script>",
                            "target_document_number": "A/2020",
                        }
                    ],
                }
            ]
        ),
    )
    response = client.get("/admin/legal-registry")
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_registry_admin_enforces_workspace_owner_isolation_and_excludes_withdrawn_reviews(
    client, monkeypatch
):
    from types import SimpleNamespace
    import app.database as db_mod

    list_ws = AsyncMock(
        return_value=[
            {
                "_id": "ws-admin-owned",
                "workspace_id": "ws-admin-owned",
                "title": "Hồ sơ của Admin",
                "analyses": [
                    {
                        "analysis_id": "rev-withdrawn",
                        "kind": "legal_effect_review",
                        "reviewed_at": "2026-11-18T00:00:00+00:00",
                        "result": {"assertions": []},
                    },
                    {
                        "analysis_id": "rev-pending",
                        "kind": "legal_effect_review",
                        "reviewed_at": "2026-11-18T01:00:00+00:00",
                        "result": {
                            "assertions": [
                                {
                                    "document_number": "168/2024/NĐ-CP",
                                    "target_document_number": "100/2019/NĐ-CP",
                                    "effective_date": "2025-01-01",
                                    "scope": "partial",
                                    "exact_quote": "Bãi bỏ một phần",
                                    "source_url": "https://vanban.chinhphu.vn/?docid=168",
                                }
                            ]
                        },
                    },
                ],
            }
        ]
    )
    monkeypatch.setattr("app.research_database.list_workspaces", list_ws)
    fake_reg_cursor = SimpleNamespace(
        to_list=AsyncMock(return_value=[{"_id": "rev-withdrawn"}])
    )
    fake_db = SimpleNamespace(
        legal_effect_registry=SimpleNamespace(find=lambda *_a, **_kw: fake_reg_cursor),
        research_workspaces=SimpleNamespace(
            find=lambda *_a, **_kw: pytest.fail("Must not run unscoped cross-tenant find()")
        ),
    )
    monkeypatch.setattr(db_mod, "db", fake_db)
    monkeypatch.setattr("app.api.legal_registry_routes.registry_records", AsyncMock(return_value=[]))

    resp = client.get("/admin/legal-registry")
    assert resp.status_code == 200
    list_ws.assert_awaited_once()
    assert list_ws.await_args.kwargs.get("user_id") == "admin"
    assert "/workspaces/ws-admin-owned/analyses/rev-pending/publish-legal-effect" in resp.text
    assert "rev-withdrawn" not in resp.text

