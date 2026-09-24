from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.services.test_retained_source_analysis import workspace


@pytest.fixture
def setup(monkeypatch):
    from app.api import retained_source_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    routes.limiter._storage.reset()
    app.dependency_overrides[routes.optional_user] = lambda: {"_id": "owner"}
    app.dependency_overrides[routes.verify_csrf] = lambda: "csrf"
    data = {"workspace_id": "w", **workspace()}
    owned = AsyncMock(return_value=(data, "client", "owner"))
    monkeypatch.setattr(routes, "_owned_workspace", owned)
    generate = AsyncMock(
        return_value={
            "status": "ok",
            "text": "Answer",
            "citations": [],
            "unanswered_parts": [],
            "context_selection": {"method": "lexical_relevance_v1", "selected": 2, "available": 3},
        }
    )
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "analyze_retained_source", generate)
    monkeypatch.setattr(routes, "save_workspace_analysis", save)
    monkeypatch.setattr(routes, "log_interaction", AsyncMock(return_value={"trace_id": "saved"}), raising=False)
    return TestClient(app), routes, generate, save


def test_collects_server_owned_pages_and_saves_scope(setup):
    client, routes, generate, save = setup
    response = client.post(
        "/workspaces/w/analyses/retained-source",
        data={"analysis_id": "first", "source_index": 0, "question": "Explain"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    source = generate.await_args.args[1]
    assert source["missing_pages"] == [3]
    record = save.await_args.args[1]
    assert record["source_scope"]["characters"] == 8
    assert record["source_scope"]["input_sha256"]
    assert record["kind"] == "retained_source_answer"
    assert record["admin_trace_status"] == "persisted"
    assert generate.await_args.kwargs["relevant_only"] is True
    logged = routes.log_interaction.await_args.kwargs
    assert logged["trace_id"] == record["analysis_id"]
    assert logged["request_status"] == "retained_source_ok"
    assert logged["retrieval_trace"]["selected_passage_count"] == 2
    assert logged["retrieval_trace"]["available_passage_count"] == 3
    assert "Explain" not in str(logged)
    assert "Answer" not in str(logged)


def test_relevant_scope_reaches_bounded_source_selector(setup):
    client, _, generate, _ = setup
    response = client.post('/workspaces/w/analyses/retained-source',
                           data={'analysis_id': 'first', 'source_index': 0,
                                 'question': 'First', 'scope': 'relevant'},
                           follow_redirects=False)
    assert response.status_code == 303
    assert generate.await_args.kwargs['relevant_only'] is True


def test_explicit_full_scope_remains_available(setup):
    client, _, generate, _ = setup
    response = client.post('/workspaces/w/analyses/retained-source',
                           data={'analysis_id': 'first', 'source_index': 0,
                                 'question': 'First', 'scope': 'full'},
                           follow_redirects=False)
    assert response.status_code == 303
    assert generate.await_args.kwargs['relevant_only'] is False


def test_workspace_change_marks_retained_source_trace(setup, monkeypatch):
    client, routes, _, save = setup
    save.return_value = False
    update = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "update_interaction_request_status", update)

    response = client.post('/workspaces/w/analyses/retained-source',
                           data={'analysis_id': 'first', 'source_index': 0,
                                 'question': 'Explain'}, follow_redirects=False)

    assert response.status_code == 409
    update.assert_awaited_once_with(
        save.await_args.args[1]['analysis_id'], 'workspace_changed',
    )


def test_retained_source_failure_has_typed_admin_error(setup):
    client, routes, generate, _ = setup
    generate.return_value = {
        'status': 'invalid_structured_response',
        'error_type': 'SourceAnswerValidationError',
    }

    response = client.post('/workspaces/w/analyses/retained-source',
                           data={'analysis_id': 'first', 'source_index': 0,
                                 'question': 'Explain'}, follow_redirects=False)

    assert response.status_code == 303
    assert routes.log_interaction.await_args.kwargs['technical_error'] == {
        'stage': 'retained_source',
        'error_type': 'invalid_structured_response',
    }


def test_missing_or_oversize_source_calls_no_provider(setup):
    client, routes, generate, save = setup
    assert (
        client.post(
            "/workspaces/w/analyses/retained-source",
            data={"analysis_id": "missing", "source_index": 0, "question": "Explain"},
        ).status_code
        == 422
    )
    generate.assert_not_awaited()
    save.assert_not_awaited()


def test_source_analysis_requires_csrf(setup):
    client, routes, generate, save = setup
    del client.app.dependency_overrides[routes.verify_csrf]
    assert (
        client.post(
            "/workspaces/w/analyses/retained-source",
            data={
                "analysis_id": "first",
                "source_index": 0,
                "question": "Explain",
                "csrf_token": "forged",
            },
        ).status_code
        == 403
    )
    generate.assert_not_awaited()


def test_saved_answer_renders_safe_text_and_links_to_server_quote(setup, monkeypatch):
    client, routes, generate, save = setup
    record = {
        "analysis_id": "answer",
        "kind": "retained_source_answer",
        "question": "Q",
        "status": "ok",
        "text": "**Supported** [p1-s0] <script>bad()</script>",
        "unanswered_parts": [],
        "source_scope": {
            "title": "Law",
            "url": "https://vanban.chinhphu.vn/",
            "characters": 8,
            "page_count": 1,
            "readable_pages": [1],
            "missing_pages": [],
            "document_sha256": "a" * 64,
        },
        "citations": [
            {
                "passage_id": "p1-s0",
                "page": 1,
                "quote": "Exact",
                "analysis_id": "read",
                "source_index": 0,
            }
        ],
    }
    monkeypatch.setattr(
        routes,
        "_owned_workspace",
        AsyncMock(
            return_value=({"workspace_id": "w", "analyses": [record]}, "c", "owner")
        ),
    )
    response = client.get("/workspaces/w/source-analysis/answer")
    assert response.status_code == 200
    assert "<strong>Supported</strong>" in response.text
    assert 'href="#report-source-p1-s0"' in response.text
    assert "<script>bad()</script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "Báo cáo chưa vượt qua bước kiểm chứng." not in response.text
    generate.assert_not_awaited()
