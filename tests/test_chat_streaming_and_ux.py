from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import routes
from app.api.dependencies import optional_user, verify_csrf
from app.rate_limit import limiter
from app.services.direct_llm import LLMGenerationResult
from app.services.guarded_answer_cache import GuardedAnswerCache
from app.services.rag_pipeline import NO_EVIDENCE_RESPONSE
from app.services.runtime_errors import GuardrailUnavailableError

ROOT = Path(__file__).resolve().parents[1]


class _InlineViolationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inline_styles: list[str] = []
        self.inline_events: list[str] = []
        self.executable_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if "style" in attr_map:
            self.inline_styles.append(tag)
        for key in attr_map:
            if key.lower().startswith("on"):
                self.inline_events.append(f"{tag}:{key}")
        if tag == "script" and not attr_map.get("src"):
            script_type = (attr_map.get("type") or "").strip().lower()
            if script_type != "application/json":
                self.executable_scripts.append(script_type or "text/javascript")


def _parse_ndjson(raw: str) -> list[dict]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


@pytest.fixture
def stream_client(monkeypatch: pytest.MonkeyPatch):
    limiter._storage.reset()
    app = FastAPI()

    @app.middleware("http")
    async def _identity(request, call_next):
        request.state.client_id = "client-stream-1"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid-csrf"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(routes.router)

    cfg = routes.settings.model_dump()
    cfg.update(
        APP_ENV="test",
        PUBLIC_GUARDRAIL_MODE="enforce",
        GUARDED_ANSWER_CACHE_ENABLED=True,
    )
    monkeypatch.setattr(routes, "settings", SimpleNamespace(**cfg))
    fresh_cache = GuardedAnswerCache(max_entries=16, ttl_seconds=300)
    monkeypatch.setattr(routes, "guarded_answer_cache", fresh_cache)
    monkeypatch.setattr(routes, "create_session", AsyncMock())
    monkeypatch.setattr(routes, "get_sessions", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "get_session_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "rename_session", AsyncMock(return_value=True))
    log = AsyncMock(return_value={})
    monkeypatch.setattr(routes, "log_interaction", log)
    return TestClient(app), log, fresh_cache


def test_chat_stream_emits_stages_deltas_and_verified_complete_card(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, log, cache = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    contexts = [
        "[45/2019/QH14, Điều 25]\n"
        "Tiêu đề: Bộ luật Lao động 2019\n"
        "Nguồn: https://vbpl.vn/bllđ\n"
        "Điều 25. Thời gian thử việc. 1. Không quá 180 ngày. 2. Không quá 60 ngày đối với công việc cần trình độ cao đẳng trở lên."
    ]
    monkeypatch.setattr(
        routes,
        "retrieve_stream_contexts",
        AsyncMock(
            return_value=(
                contexts,
                "thời gian thử việc trình độ đại học",
                {"t_retrieval": 0.12, "retrieval_status": "ok", "retrieval_diagnostics": {}},
                None,
            )
        ),
    )

    async def _fake_stream(*_args, **_kwargs):
        # Deliberately cite Khoản 1 for 60 ngày so verify_clause_citations corrects it to Khoản 2!
        yield "Thời gian thử việc không quá 60 ngày theo "
        yield "Khoản 1 Điều 25 [45/2019/QH14, Điều 25]."
        yield LLMGenerationResult(
            text="Thời gian thử việc không quá 60 ngày theo Khoản 1 Điều 25 [45/2019/QH14, Điều 25].",
            observed_provider="gemini",
            observed_model="gemini-2.5-flash",
            observed=True,
            status="success",
        )

    monkeypatch.setattr(routes, "stream_llm_response_with_metadata", _fake_stream)

    resp = client.post(
        "/chat/stream",
        data={
            "message": "Thời gian thử việc tối đa với trình độ đại học là bao lâu?",
            "csrf_token": "valid-csrf",
            "session_id": "sess-1",
            "llm_provider": "gemini",
            "llm_model": "gemini-2.5-flash",
            "web_mode": "auto",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert resp.headers["cache-control"] == "no-store"
    events = _parse_ndjson(resp.text)
    stages = [e["label"] for e in events if e["type"] == "stage"]
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    completes = [e for e in events if e["type"] == "complete"]

    assert len(stages) >= 3
    assert "".join(deltas).startswith("Thời gian thử việc không quá 60 ngày")
    assert len(completes) == 1
    complete = completes[0]
    assert complete["session_id"] == "sess-1"
    assert complete["guardrail_adjusted"] is True
    # Clause citation guard corrected Khoản 1 -> Khoản 2 in final server HTML & cache!
    assert "Khoản 2 Điều 25" in complete["html"]
    assert log.await_args.kwargs["request_status"] == "ok"
    assert "Khoản 2 Điều 25" in log.await_args.kwargs["bot_response"]
    assert len(cache) == 1


def test_chat_stream_blocks_unsafe_output_before_cache_and_replaces_preview(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, log, cache = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(
        routes,
        "check_output_guardrails",
        AsyncMock(return_value=(False, "Câu trả lời bị chặn vì thiếu căn cứ xác thực.")),
    )
    monkeypatch.setattr(
        routes,
        "retrieve_stream_contexts",
        AsyncMock(return_value=(["[45/2019/QH14, Điều 25]\nNội dung điều 25."], "thử việc", {}, None)),
    )

    async def _fake_stream(*_args, **_kwargs):
        yield "Nội dung bịa đặt chưa kiểm chứng"
        yield LLMGenerationResult(
            text="Nội dung bịa đặt chưa kiểm chứng",
            observed_provider="groq",
            observed_model="openai/gpt-oss-20b",
            observed=True,
            status="success",
        )

    monkeypatch.setattr(routes, "stream_llm_response_with_metadata", _fake_stream)

    resp = client.post(
        "/chat/stream",
        data={
            "message": "Thời gian thử việc tối đa là bao lâu?",
            "csrf_token": "valid-csrf",
            "session_id": "sess-2",
        },
    )
    events = _parse_ndjson(resp.text)
    complete = next(e for e in events if e["type"] == "complete")
    assert complete["guardrail_adjusted"] is True
    assert "Câu trả lời bị chặn vì thiếu căn cứ xác thực." in complete["html"]
    assert "Nội dung bịa đặt chưa kiểm chứng" not in complete["html"]
    assert log.await_args.kwargs["request_status"] == "blocked_output"
    assert len(cache) == 0


def test_chat_stream_empty_contexts_skips_llm_and_runs_output_guardrail(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, log, _ = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    output_guard = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(routes, "check_output_guardrails", output_guard)
    monkeypatch.setattr(
        routes,
        "retrieve_stream_contexts",
        AsyncMock(return_value=([], "câu hỏi hiếm", {"retrieval_status": "ok"}, None)),
    )
    forbidden_llm = AsyncMock(side_effect=AssertionError("LLM must not be called on empty contexts"))
    monkeypatch.setattr(routes, "stream_llm_response_with_metadata", forbidden_llm)

    resp = client.post(
        "/chat/stream",
        data={"message": "Quy định hiếm không có trong kho?", "csrf_token": "valid-csrf", "session_id": "sess-empty"},
    )
    events = _parse_ndjson(resp.text)
    complete = next(e for e in events if e["type"] == "complete")
    assert NO_EVIDENCE_RESPONSE in complete["html"]
    output_guard.assert_awaited_once()
    assert log.await_args.kwargs["request_status"] == "no_evidence"


def test_chat_stream_guardrail_503_emits_typed_error_event(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, log, _ = stream_client
    monkeypatch.setattr(
        routes,
        "check_input_guardrails",
        AsyncMock(side_effect=GuardrailUnavailableError("input", "timeout")),
    )
    resp = client.post(
        "/chat/stream",
        data={"message": "Câu hỏi hợp lệ", "csrf_token": "valid-csrf", "session_id": "sess-err"},
    )
    assert resp.status_code == 200
    events = _parse_ndjson(resp.text)
    err = next(e for e in events if e["type"] == "error")
    assert err["status"] == 503
    assert err["message"]
    assert log.await_args.kwargs["request_status"] == "technical_error"


def test_new_session_placeholder_autotitles_on_first_message_in_chat_and_stream(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(
        routes,
        "get_sessions",
        AsyncMock(return_value=[{"session_id": "new-sess", "title": "Hội thoại mới"}]),
    )
    monkeypatch.setattr(routes, "get_session_messages", AsyncMock(return_value=[]))
    rename_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "rename_session", rename_mock)
    monkeypatch.setattr(
        routes,
        "run_advanced_rag",
        AsyncMock(return_value=("Câu trả lời", ["[45/2019/QH14, Điều 25]\nCăn cứ"], {})),
    )

    first_question = "Mức phạt nồng độ cồn xe máy theo Nghị định 168/2024/NĐ-CP là bao nhiêu?"
    resp_chat = client.post(
        "/chat",
        data={"message": first_question, "csrf_token": "valid-csrf", "session_id": "new-sess"},
    )
    assert resp_chat.status_code == 200
    assert rename_mock.await_args.args[1] == first_question[:48]
    assert resp_chat.headers.get("hx-trigger") == "load-sessions"

    rename_mock.reset_mock()
    monkeypatch.setattr(
        routes,
        "retrieve_stream_contexts",
        AsyncMock(return_value=([], first_question, {"retrieval_status": "ok"}, None)),
    )
    resp_stream = client.post(
        "/chat/stream",
        data={"message": first_question, "csrf_token": "valid-csrf", "session_id": "new-sess"},
    )
    complete = next(e for e in _parse_ndjson(resp_stream.text) if e["type"] == "complete")
    assert complete["title"] == first_question[:48]
    assert rename_mock.await_args.args[1] == first_question[:48]


def test_index_renders_dev_admin_controls_starter_chips_stop_button_and_scroll_css(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_mod

    client = TestClient(main_mod.app)
    html = client.get("/").text

    assert 'data-action="stop-chat"' in html
    assert 'id="chat-stop"' in html
    assert html.count('data-prompt="') >= 4
    assert 'class="workflow-grid"' in html
    assert "data-llm-target" in html
    assert 'name="web_mode"' in html

    parser = _InlineViolationParser()
    parser.feed(html)
    assert not parser.inline_styles
    assert not parser.inline_events
    assert not parser.executable_scripts

    css = (ROOT / "app/static/css/vietlex-redesign.css").read_text(encoding="utf-8")
    assert "min-width:761px" in css or "min-width: 761px" in css
    assert "overflow-y:auto" in css or "overflow-y: auto" in css
    assert ".button[hidden]" in css and "display:none" in css
    assert "justify-content:flex-end" in css or "justify-content: flex-end" in css
    assert 'id="chat-input" name="message" rows="1"' in html


def test_public_production_user_cannot_override_web_mode_or_see_dev_controls_and_all_templates_pass_csp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prod_settings = SimpleNamespace(APP_ENV="production")
    controls = routes.build_index_llm_controls(None, prod_settings)
    assert controls == {"can_select_llm_route": False, "llm_targets": []}
    assert routes._resolve_web_mode("force", None, prod_settings) == "auto"
    assert (
        routes._resolve_web_mode(
            "force",
            {"_id": "adm", "role": "admin", "status": "active", "email_verified": True},
            prod_settings,
        )
        == "force"
    )

    for rel_path in (
        "app/templates/index.html",
        "app/templates/chat_message.html",
        "app/templates/legal_search.html",
        "app/templates/legal_document.html",
        "app/templates/research_workspace.html",
        "app/templates/workspace_evidence.html",
        "app/templates/admin_legal_registry.html",
    ):
        tpl_text = (ROOT / rel_path).read_text(encoding="utf-8")
        parser = _InlineViolationParser()
        parser.feed(tpl_text)
        assert not parser.inline_styles, f"Inline style in {rel_path}: {parser.inline_styles}"
        assert not parser.inline_events, f"Inline handler in {rel_path}: {parser.inline_events}"
        assert not parser.executable_scripts, f"Inline script in {rel_path}: {parser.executable_scripts}"


def test_post_chat_honors_web_mode_and_workspace_template_serializes_batch_fields(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    rag_mock = AsyncMock(return_value=("Câu trả lời", ["[45/2019/QH14, Điều 25]\nCăn cứ"], {}))
    monkeypatch.setattr(routes, "run_advanced_rag", rag_mock)

    resp = client.post(
        "/chat",
        data={
            "message": "Thời gian thử việc tối đa?",
            "csrf_token": "valid-csrf",
            "session_id": "sess-webmode",
            "web_mode": "force",
        },
    )
    assert resp.status_code == 200
    assert rag_mock.await_args.kwargs.get("web_mode") == "force"

    ws_tpl = (ROOT / "app/templates/research_workspace.html").read_text(encoding="utf-8")
    assert "'document_id'" in ws_tpl and "'input_sha256'" in ws_tpl and "'batch_id'" in ws_tpl
    assert "data-workspace-llm-target" in ws_tpl


def test_workspace_free_web_research_web_mode_off_disables_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from app.api import free_web_research_routes as fwr_routes
    from app.services.free_web_research import _configured_provider
    from app.services.tavily_search import is_tavily_extract_enabled, is_tavily_search_enabled

    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid-csrf"
    app.dependency_overrides[optional_user] = lambda: {
        "_id": "admin-1",
        "role": "admin",
        "status": "active",
        "email_verified": True,
    }
    app.include_router(fwr_routes.router)

    base_settings = SimpleNamespace(
        APP_ENV="development",
        FREE_WEB_RESEARCH_ENABLED=True,
        OFFICIAL_WEB_RESEARCH_ENABLED=True,
        TAVILY_SEARCH_ENABLED=True,
        TAVILY_EXTRACT_ENABLED=True,
        TAVILY_API="tvly-test-key",
        FREE_WEB_RESEARCH_TOTAL_BUDGET_SECONDS=30.0,
        FREE_WEB_RESEARCH_SAVE_BUDGET_SECONDS=5.0,
        FREE_WEB_RESEARCH_PROVIDER_TIMEOUT_SECONDS=2.0,
    )
    assert is_tavily_search_enabled(base_settings) is True
    assert is_tavily_extract_enabled(base_settings) is True
    assert "tavily" in dict(_configured_provider(base_settings).providers)

    monkeypatch.setattr(fwr_routes, "get_settings", lambda: base_settings)
    monkeypatch.setattr(
        fwr_routes,
        "_owned_workspace",
        AsyncMock(return_value=({"workspace_id": "ws-1", "analyses": []}, "cli-1", "admin-1")),
    )
    monkeypatch.setattr(
        fwr_routes,
        "begin_free_research_run",
        AsyncMock(
            return_value={
                "outcome": "started",
                "analysis": {"analysis_id": "run-1", "status": "running", "result": {}},
            }
        ),
    )
    monkeypatch.setattr(fwr_routes, "checkpoint_free_research_run", AsyncMock(return_value=True))

    captured_settings = []

    async def _fake_stream(_question, *, settings, **_kwargs):
        captured_settings.append(settings)
        yield {"type": "terminal", "status": "complete", "source_count": 0}

    monkeypatch.setattr(fwr_routes, "stream_free_web_research", _fake_stream)

    client = TestClient(app)
    resp = client.post(
        "/workspaces/ws-1/research/read",
        data={
            "question": "Khấu trừ tiền lương người lao động theo Bộ luật Lao động",
            "run_id": str(uuid.uuid4()),
            "refresh": "false",
            "web_mode": "off",
            "csrf_token": "valid-csrf",
        },
    )
    assert resp.status_code == 200
    assert len(captured_settings) == 1
    eff = captured_settings[0]
    assert is_tavily_search_enabled(eff) is False
    assert is_tavily_extract_enabled(eff) is False
    assert "tavily" not in dict(_configured_provider(eff).providers)


def test_greeting_in_chat_and_stream_skips_retrieval_and_hides_claim_support_and_recovery(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import direct_llm, rag_pipeline

    client, log, _cache = stream_client
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    forbidden = AsyncMock(side_effect=AssertionError("retrieval/LLM forbidden for greeting"))
    monkeypatch.setattr(routes, "retrieve_stream_contexts", forbidden)
    monkeypatch.setattr(routes, "stream_llm_response_with_metadata", forbidden)
    monkeypatch.setattr(direct_llm, "generate_llm_response_with_metadata", forbidden)
    monkeypatch.setattr(rag_pipeline, "retrieve_configured_legal_evidence", forbidden)
    monkeypatch.setattr(rag_pipeline, "generate_response_with_metadata", forbidden)

    stream_resp = client.post(
        "/chat/stream",
        data={"message": "Xin chào", "csrf_token": "valid-csrf"},
    )
    assert stream_resp.status_code == 200
    events = _parse_ndjson(stream_resp.text)
    stages = [ev.get("stage") for ev in events if ev.get("type") == "stage"]
    assert "corpus_retrieval" not in stages
    assert "web_supplement" not in stages
    complete = next(ev for ev in events if ev.get("type") == "complete")
    stream_html = complete["html"]
    assert "VietLex" in stream_html
    assert "Liên kết bằng chứng" not in stream_html
    assert "Nguồn pháp lý truy xuất" not in stream_html
    assert "Tìm nguồn chính thức trong hồ sơ" not in stream_html
    assert log.call_args.kwargs["request_status"] == "unsupported_intent"

    chat_resp = client.post(
        "/chat",
        data={"message": "Xin chào", "csrf_token": "valid-csrf"},
    )
    assert chat_resp.status_code == 200
    assert "VietLex" in chat_resp.text
    assert "Liên kết bằng chứng" not in chat_resp.text
    assert "Nguồn pháp lý truy xuất" not in chat_resp.text
    assert "Tìm nguồn chính thức trong hồ sơ" not in chat_resp.text
    assert log.call_args.kwargs["request_status"] == "unsupported_intent"
    forbidden.assert_not_awaited()


def test_history_replay_hides_claim_support_and_recovery_for_non_retrieval_statuses(
    stream_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _log, _cache = stream_client
    monkeypatch.setattr(
        routes,
        "get_session_messages",
        AsyncMock(
            return_value=[
                {
                    "trace_id": "trace-hist-1",
                    "user_query": "Xin chào",
                    "bot_response": "Xin chào! Tôi là VietLex — trợ lý tra cứu và nghiên cứu pháp luật Việt Nam.",
                    "contexts": [],
                    "request_status": "unsupported_intent",
                },
                {
                    "trace_id": "trace-hist-2",
                    "user_query": "Tôi chỉ nói bên kia giữ tiền của tôi?",
                    "bot_response": "Tôi chưa đủ dữ kiện để kết luận.",
                    "contexts": [],
                    "request_status": "clarification",
                },
            ]
        ),
    )
    resp = client.get("/sessions/sess-greeting-1")
    assert resp.status_code == 200
    assert "Liên kết bằng chứng" not in resp.text
    assert "Tìm nguồn chính thức trong hồ sơ" not in resp.text


