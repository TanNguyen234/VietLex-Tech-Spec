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
    assert "Lập kế hoạch nghiên cứu sâu" in detail.text


def test_workspace_hides_official_research_when_feature_is_disabled(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": [], "analyses": []}),
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.settings.OFFICIAL_WEB_RESEARCH_ENABLED", False
    )

    response = client.get("/workspaces/w-1")

    assert response.status_code == 200
    assert "Lập kế hoạch nghiên cứu sâu" not in response.text


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


def test_deep_research_plan_is_previewed_without_provider_call(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": [], "analyses": []}),
    )

    response = client.post(
        "/workspaces/w-1/research/plan",
        data={"question": "Điều kiện chấm dứt hợp đồng lao động?"},
    )

    assert response.status_code == 200
    assert len(response.json()["steps"]) == 5
    assert response.json()["status"] == "draft"
    assert client.post(
        "/workspaces/w-1/research/plan", data={"question": "   "}
    ).status_code == 422


def test_deep_research_run_persists_owner_scoped_result_and_provider_calls(
    client, monkeypatch
) -> None:
    from app.services.deep_research import DeepResearchResult, ResearchStepResult

    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "evidence": [], "analyses": []}),
    )
    plan_response = client.post(
        "/workspaces/w-1/research/plan", data={"question": "Câu hỏi pháp lý"}
    )
    result = DeepResearchResult(
        status="partial",
        question="Câu hỏi pháp lý",
        plan_id=plan_response.json()["plan_id"],
        steps=[
            ResearchStepResult(
                step_id="legal_basis",
                title="Căn cứ pháp lý",
                query="Câu hỏi pháp lý căn cứ pháp lý",
                status="no_results",
            )
        ],
        provider="chinhphu_official_portal",
        model="webforms-search-v1",
    )
    monkeypatch.setattr(
        "app.api.workspace_routes.run_deep_research", AsyncMock(return_value=result)
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.save_workspace_analysis", save)
    log = AsyncMock(return_value={})
    monkeypatch.setattr("app.api.workspace_routes.log_interaction", log)
    update_status = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.api.workspace_routes.update_interaction_request_status", update_status
    )

    response = client.post(
        "/workspaces/w-1/research/run",
        data={"plan": plan_response.text},
    )

    assert response.status_code == 200
    saved = save.await_args.args[1]
    assert saved["kind"] == "deep_research"
    assert saved["status"] == "partial"
    assert save.await_args.kwargs["user_id"] is None
    assert saved["plan"]["plan_id"] == saved["result"]["plan_id"]
    assert saved["admin_trace_status"] == "unavailable"
    assert log.await_args.kwargs["request_metadata"]["path"].endswith("/research/run")

    save.return_value = False
    changed = client.post(
        "/workspaces/w-1/research/run",
        data={"plan": plan_response.text},
    )
    assert changed.status_code == 409
    failed_analysis_id = save.await_args.args[1]["analysis_id"]
    update_status.assert_awaited_once_with(failed_analysis_id, "workspace_changed")


def test_workspace_upload_keeps_original_private_and_returns_only_metadata(
    client, monkeypatch
) -> None:
    from app.services.workspace_documents import (
        ExtractedWorkspaceDocument,
        WorkspaceClause,
    )

    monkeypatch.setattr(
        "app.api.workspace_routes.get_workspace",
        AsyncMock(return_value={"workspace_id": "w-1", "documents": []}),
    )
    extracted = ExtractedWorkspaceDocument(
        document_id="a" * 24,
        filename="contract.txt",
        file_type="txt",
        media_type="text/plain",
        sha256="a" * 64,
        size_bytes=20,
        extracted_characters=12,
        clauses=[
            WorkspaceClause(
                clause_id=f"{'a' * 24}-001",
                title="Điều 1",
                text="Nội dung thật",
                order=1,
            )
        ],
    )
    extract = pytest.importorskip("unittest.mock").Mock(return_value=extracted)
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.extract_workspace_document", extract)
    monkeypatch.setattr("app.api.workspace_routes.save_workspace_document", save)

    response = client.post(
        "/workspaces/w-1/documents",
        data={"csrf_token": "valid"},
        files={"document": ("contract.txt", b"raw file bytes", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["document_id"] == "a" * 24
    persisted = save.await_args.args[1]
    assert persisted["clauses"][0]["text"] == "Nội dung thật"
    assert save.await_args.kwargs['original_bytes'] == b"raw file bytes"
    assert response.json()['original_available'] is True
    assert 'original_bytes' not in response.text


def test_original_download_is_owner_scoped_and_forces_attachment(client, monkeypatch):
    monkeypatch.setattr('app.api.workspace_routes.get_workspace', AsyncMock(return_value={'documents': []}))
    original = AsyncMock(return_value={'filename': 'hợp đồng.txt', 'original_bytes': b'private original'})
    monkeypatch.setattr('app.api.workspace_routes.get_workspace_original', original, raising=False)
    response = client.get('/workspaces/w-1/documents/doc-1/original')
    assert response.status_code == 200
    assert response.content == b'private original'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'].startswith('attachment;')
    original.assert_awaited_once_with('w-1', 'doc-1', 'owner-a', user_id=None)
    monkeypatch.setattr('app.api.workspace_routes.get_workspace', AsyncMock(return_value=None))
    original.reset_mock()
    assert client.get('/workspaces/w-1/documents/doc-1/original').status_code == 404
    original.assert_not_awaited()


def test_document_clause_pin_resolves_text_server_side(client, monkeypatch) -> None:
    document_id = "a" * 24
    clause_id = f"{document_id}-001"
    workspace = {
        "workspace_id": "w-1",
        "documents": [
            {
                "document_id": document_id,
                "filename": "contract.txt",
                "clauses": [
                    {
                        "clause_id": clause_id,
                        "title": "Điều 1",
                        "text": "Server clause",
                        "page": None,
                    }
                ],
            }
        ],
        "evidence": [],
    }
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value=workspace))
    pin = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.pin_workspace_evidence", pin)

    response = client.post(
        f"/workspaces/w-1/documents/{document_id}/clauses/{clause_id}/pin",
        headers={"X-CSRF-Token": "valid"},
    )

    assert response.status_code == 200
    evidence = pin.await_args.args[1]
    assert evidence["original"].endswith("Server clause")
    assert evidence["workspace_document_id"] == document_id
    forged = client.post(
        f"/workspaces/w-1/documents/{document_id}/clauses/{document_id}-099/pin",
        headers={"X-CSRF-Token": "valid"},
    )
    assert forged.status_code == 422


def test_contract_review_uses_selected_server_clauses_and_legal_evidence(
    client, monkeypatch
) -> None:
    from app.services.workspace_documents import ContractFinding, ContractReviewResult

    document_id = "b" * 24
    clause_id = f"{document_id}-001"
    workspace = {
        "workspace_id": "w-1",
        "documents": [
            {
                "document_id": document_id,
                "filename": "agreement.docx",
                "clauses": [{"clause_id": clause_id, "title": "Điều 1", "text": "Server clause"}],
            }
        ],
        "evidence": [{"evidence_id": "ev-law", "original": "Điều luật", "citation": "Điều 1"}],
    }
    monkeypatch.setattr("app.api.workspace_routes.get_workspace", AsyncMock(return_value=workspace))
    generated = ContractReviewResult(
        findings=[
            ContractFinding(
                clause_id=clause_id,
                risk_level="review",
                issue="Cần đối chiếu",
                legal_evidence_ids=["ev-law"],
                recommendation="Kiểm tra thêm",
                support_state="evidence_linked",
            )
        ]
    )
    generate = AsyncMock(return_value=(generated, {"provider": "test", "model": "model"}))
    monkeypatch.setattr("app.api.workspace_routes.generate_contract_review", generate)
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.workspace_routes.save_workspace_analysis", save)
    log = AsyncMock(return_value={"trace_id": "trace"})
    monkeypatch.setattr("app.api.workspace_routes.log_interaction", log)

    response = client.post(
        f"/workspaces/w-1/documents/{document_id}/review",
        data={"clause_ids": clause_id, "legal_evidence_ids": "ev-law"},
    )

    assert response.status_code == 200
    assert generate.await_args.args[0][0]["text"] == "Server clause"
    assert generate.await_args.args[1][0]["evidence_id"] == "ev-law"
    assert save.await_args.args[1]["kind"] == "contract_review"
    assert save.await_args.kwargs["required_document_id"] == document_id
    assert save.await_args.args[1]["admin_trace_status"] == "persisted"
    assert log.await_args.kwargs["retrieval_trace"]["mode"] == "user_document_review"
    assert log.await_args.kwargs['contexts'] == []
    assert 'agreement.docx' not in log.await_args.kwargs['user_query']
    assert 'Cần đối chiếu' not in log.await_args.kwargs['bot_response']

    workspace["evidence"].append(
        {
            "evidence_id": "ev-user",
            "source_kind": "user_document",
            "original": "Hợp đồng khác",
        }
    )
    invalid_law = client.post(
        f"/workspaces/w-1/documents/{document_id}/review",
        data={"clause_ids": clause_id, "legal_evidence_ids": "ev-user"},
    )
    assert invalid_law.status_code == 422
    assert generate.await_count == 1
