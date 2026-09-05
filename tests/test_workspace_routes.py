from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user, verify_csrf, verify_csrf_header
from app.services.research_analysis import (
    ComparisonFinding,
    ComparisonResult,
    ObligationMatrixResult,
    ObligationRow,
)


@pytest.fixture
def client():
    from app.api.workspace_routes import router

    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[verify_csrf_header] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    return TestClient(app)


def test_create_workspace_uses_request_owner(client, monkeypatch) -> None:
    create = AsyncMock(return_value={"workspace_id": "w-1"})
    monkeypatch.setattr("app.api.workspace_routes.create_workspace", create)
    monkeypatch.setattr("app.api.workspace_routes.uuid.uuid4", lambda: "w-1")

    response = client.post(
        "/workspaces",
        data={"title": "Hồ sơ lao động", "description": "Thử việc"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/workspaces/w-1"
    create.assert_awaited_once_with(
        "w-1", "Hồ sơ lao động", "Thử việc", "owner-a", user_id=None
    )


def test_workspace_detail_is_owner_scoped(client, monkeypatch) -> None:
    get = AsyncMock(return_value=None)
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", get)

    response = client.get("/workspaces/not-owned")

    assert response.status_code == 404
    get.assert_awaited_once_with("not-owned", "owner-a", user_id=None)


def test_workspace_list_and_detail_render_empty_states(client, monkeypatch) -> None:
    workspace = {
        "workspace_id": "w-1",
        "title": "Hồ sơ lao động",
        "description": "Thử việc",
        "evidence": [],
        "analyses": [],
    }
    monkeypatch.setattr(
        "app.api.workspace_routes.list_workspaces", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=workspace)
    )

    listing = client.get("/workspaces")
    detail = client.get("/workspaces/w-1")

    assert listing.status_code == 200
    assert listing.cookies.get("csrf_token")
    assert listing.cookies["csrf_token"] in listing.text
    assert "Chưa có hồ sơ" in listing.text
    assert detail.status_code == 200
    assert "Chưa có bằng chứng được ghim" in detail.text


def test_pin_evidence_resolves_owned_trace_and_index(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": []}),
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.get_owned_interaction",
        AsyncMock(
            return_value={
                "trace_id": "trace-1",
                "bot_response": "Theo Điều 25...",
                "contexts": [
                    "[45/2019/QH14, Điều 25]\nID tài liệu: 123\nTrích đoạn gốc"
                ],
            }
        ),
    )
    pin = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.pin_workspace_evidence", pin)

    response = client.post(
        "/workspaces/w-1/evidence",
        data={"trace_id": "trace-1", "evidence_index": "0", "note": "Quan trọng"},
    )

    assert response.status_code == 200
    evidence = pin.await_args.args[1]
    assert evidence["original"].endswith("Trích đoạn gốc")
    assert evidence["document_id"] == 123
    assert evidence["note"] == "Quan trọng"
    assert evidence["introduced_by_claim"] == "Theo Điều 25..."


def test_pin_rejects_invalid_evidence_index(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": []}),
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.get_owned_interaction",
        AsyncMock(return_value={"contexts": ["one"]}),
    )

    response = client.post(
        "/workspaces/w-1/evidence",
        data={"trace_id": "trace-1", "evidence_index": "4"},
    )

    assert response.status_code == 422


def test_selected_analysis_fails_without_selected_workspace_evidence(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": []}),
    )
    generate = AsyncMock()
    monkeypatch.setattr(
        "app.api.workspace_routes.generate_selected_evidence_answer", generate
    )

    response = client.post(
        "/workspaces/w-1/analyses/selected",
        data={"question": "Phân tích", "evidence_ids": "missing"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "insufficient_evidence"
    generate.assert_not_awaited()


def test_selected_analysis_passes_only_server_resolved_evidence(
    client, monkeypatch
) -> None:
    selected = {"evidence_id": "ev-1", "original": "Điều 1", "citation": "Điều 1"}
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": [selected]}),
    )
    generate = AsyncMock(
        return_value={
            "status": "ok",
            "text": "Kết quả",
            "provider": "test",
            "model": "test-model",
        }
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.generate_selected_evidence_answer", generate
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.save_workspace_analysis", AsyncMock(return_value=True)
    )

    response = client.post(
        "/workspaces/w-1/analyses/selected",
        data={"question": "Phân tích", "evidence_ids": "ev-1"},
    )

    assert response.status_code == 200
    assert response.json()["evidence_scope"] == 1
    assert generate.await_args.args[1] == [selected]

    rejected = client.post(
        "/workspaces/w-1/analyses/selected",
        data={"question": "Phân tích", "evidence_ids": "ev-1,forged"},
    )
    assert rejected.status_code == 422
    assert generate.await_count == 1


def test_compare_persists_validated_evidence_links(client, monkeypatch) -> None:
    evidence = [
        {"evidence_id": "ev-a", "original": "A"},
        {"evidence_id": "ev-b", "original": "B"},
    ]
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": evidence}),
    )
    generated = ComparisonResult(
        findings=[
            ComparisonFinding(
                topic="Thời hạn",
                document_a_finding="30 ngày",
                document_b_finding="45 ngày",
                interpretation="Khác nhau",
                evidence_a=["ev-a"],
                evidence_b=["ev-b"],
                support_state="directly_supported",
                change_type="difference",
            )
        ]
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.generate_comparison",
        AsyncMock(return_value=(generated, {"provider": "test", "model": "model"})),
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.save_workspace_analysis", save)

    response = client.post(
        "/workspaces/w-1/analyses/compare",
        data={"evidence_a": "ev-a", "evidence_b": "ev-b"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["findings"][0]["evidence_a"] == ["ev-a"]
    assert save.await_args.args[1]["status"] == "ok"
    assert save.await_args.args[1]["evidence_snapshot"][0]["original"] == "A"


def test_workspace_mutations_enforce_csrf_and_authenticated_owner(
    client, monkeypatch
) -> None:
    client.app.dependency_overrides.pop(verify_csrf)
    client.app.dependency_overrides.pop(verify_csrf_header)
    assert (
        client.post(
            "/workspaces", data={"title": "X", "csrf_token": "forged"}
        ).status_code
        == 403
    )
    assert client.delete("/workspaces/w-1").status_code == 403
    client.app.dependency_overrides[verify_csrf] = lambda: "valid"
    client.app.dependency_overrides[verify_csrf_header] = lambda: "valid"
    client.app.dependency_overrides[optional_user] = lambda: {"_id": "user-1"}
    owned = AsyncMock(return_value={"workspace_id": "w-1", "evidence": []})
    update = AsyncMock(return_value=True)
    delete = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", owned)
    monkeypatch.setattr("app.api.workspace_routes.update_workspace", update)
    monkeypatch.setattr("app.api.workspace_routes.delete_workspace", delete)
    assert (
        client.post(
            "/workspaces/w-1", data={"title": "Renamed"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert client.delete("/workspaces/w-1").status_code == 200
    assert all(call.kwargs["user_id"] == "user-1" for call in owned.await_args_list)
    delete.assert_awaited_once_with("w-1", "owner-a", user_id="user-1")


def test_malformed_model_output_is_persisted_as_error(client, monkeypatch) -> None:
    from pydantic import ValidationError
    from app.services.research_analysis import parse_comparison

    try:
        parse_comparison("invalid-json", {"ev-a", "ev-b"})
    except ValidationError as error:
        invalid = error
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(
            return_value={
                "evidence": [{"evidence_id": "ev-a"}, {"evidence_id": "ev-b"}]
            }
        ),
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.generate_comparison", AsyncMock(side_effect=invalid)
    )
    saved = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.save_workspace_analysis", saved)
    response = client.post(
        "/workspaces/w-1/analyses/compare",
        data={"evidence_a": "ev-a", "evidence_b": "ev-b"},
    )
    assert response.status_code == 502
    assert response.json()["status"] == "invalid_structured_response"
    assert "invalid-json" not in response.text


def test_saved_analysis_renders_with_datetimes_and_escaped_sources(
    client, monkeypatch
) -> None:
    from datetime import datetime, timezone

    workspace = {
        "workspace_id": "w-1",
        "title": "Research",
        "description": "",
        "evidence": [],
        "analyses": [
            {
                "kind": "comparison",
                "status": "ok",
                "created_at": datetime.now(timezone.utc),
                "result": {"findings": []},
            }
        ],
    }
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace", AsyncMock(return_value=workspace)
    )
    response = client.get("/workspaces/w-1")
    assert response.status_code == 200
    assert "data-saved-analysis" in response.text


def test_obligation_matrix_returns_typed_degraded_state(client, monkeypatch) -> None:
    evidence = [{"evidence_id": "ev-1", "original": "Bên A phải báo cáo."}]
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": evidence}),
    )
    generated = ObligationMatrixResult(
        rows=[
            ObligationRow(
                subject="Bên A",
                action="Báo cáo",
                modality="required",
                evidence_ids=["ev-1"],
                support_state="needs_verification",
            )
        ]
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.generate_obligation_matrix",
        AsyncMock(return_value=(generated, {"provider": "test", "model": "model"})),
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.save_workspace_analysis", AsyncMock(return_value=True)
    )

    response = client.post(
        "/workspaces/w-1/analyses/obligations", data={"evidence_ids": "ev-1"}
    )

    assert response.status_code == 200
    assert response.json()["result"]["rows"][0]["modality"] == "required"
