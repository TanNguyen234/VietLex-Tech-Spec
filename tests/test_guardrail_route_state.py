from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.api.dependencies import optional_user, verify_csrf
from app.config import Settings
from app.rate_limit import limiter
from app.services.research_presenter import build_public_retrieval_trace
from app.services.runtime_errors import GuardrailUnavailableError, SourceReadError


@pytest.fixture
def guarded_chat(monkeypatch):
    limiter._storage.reset()
    app = FastAPI()
    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(routes.router)
    config = routes.settings.model_dump()
    config.update(PUBLIC_NEMO_DEFAULT_ENABLED=False, PUBLIC_GUARDRAIL_MODE=None)
    monkeypatch.setattr(routes, "settings", SimpleNamespace(**config))
    log = AsyncMock()
    cache = AsyncMock(return_value=None)
    save = AsyncMock()
    rag = AsyncMock(return_value=("Original answer", ["Evidence"], {}))
    monkeypatch.setattr(routes, "log_interaction", log)
    monkeypatch.setattr(routes, "semantic_cache_query_allowed", lambda _: True)
    monkeypatch.setattr(routes, "check_semantic_cache", cache)
    monkeypatch.setattr(routes, "save_to_semantic_cache", save)
    monkeypatch.setattr(routes, "run_advanced_rag", rag)
    return TestClient(app), log, cache, save, rag


def post(client, **options):
    return client.post("/chat", data={"message": "Điều kiện thử việc?", "csrf_token": "valid", "session_id": "s-1", **options})


def test_generation_error_is_http_failure_with_trace_and_unknown_output_safety(guarded_chat, monkeypatch):
    client, log, _, _, rag = guarded_chat
    monkeypatch.setattr(routes, 'check_input_guardrails', AsyncMock(return_value=(True, '')))
    output = AsyncMock(side_effect=AssertionError('failed generation must not be assessed'))
    monkeypatch.setattr(routes, 'check_output_guardrails', output)
    rag.return_value = ('Provider unavailable', ['Evidence'], {'generation_status': 'authentication_failed'})
    response = post(client)
    assert response.status_code == 503
    assert 'data-trace-id=' in response.text
    saved = log.await_args.kwargs
    assert saved['request_status'] == 'technical_error'
    assert saved['guardrail_state']['output_safe'] is None
    output.assert_not_awaited()


def test_guardrail_mode_is_mandatory():
    assert Settings(_env_file=None).PUBLIC_GUARDRAIL_MODE == 'enforce'


def test_source_transport_kind_keeps_existing_error_contract():
    error = SourceReadError("source_transport_error", transport_kind="connect_timeout")
    assert str(error) == error.kind == "source_transport_error"
    assert error.transport_kind == "connect_timeout"
    assert SourceReadError("source_timeout").transport_kind is None


@pytest.mark.asyncio
async def test_off_remains_an_explicit_offline_primitive():
    state = routes._guardrail_state('off')
    forbidden = AsyncMock(side_effect=AssertionError('offline off must not call provider'))
    assert await routes._run_guardrail('input', 'off', state, forbidden, 'query') == (True, '', 0.0)
    assert state['input_safe'] is None
    forbidden.assert_not_awaited()


@pytest.mark.parametrize("stage", ["input", "output"])
def test_enforce_error_persists_unknown_and_typed_state(guarded_chat, monkeypatch, stage):
    client, log, _, _, rag = guarded_chat
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, f"check_{stage}_guardrails", AsyncMock(side_effect=GuardrailUnavailableError(stage, "timeout")))
    assert post(client, nemo_enabled="true").status_code == 503
    saved = log.await_args.kwargs
    assert saved["request_status"] == "technical_error"
    assert saved.get("rejection_reason") is None
    state = saved["guardrail_state"]
    assert state["status"] == "error"
    assert state[f"{stage}_safe"] is None
    assert state["stages"][stage]["error"] == {"type": "GuardrailUnavailableError", "stage": stage, "reason": "timeout"}
    if stage == "input":
        rag.assert_not_awaited()
        assert state["stages"]["output"]["status"] == "not_run"
    else:
        assert state["input_safe"] is True


@pytest.mark.parametrize("stage", ["input", "output"])
@pytest.mark.parametrize("outcome", ["rejected", "error"])
def test_legacy_shadow_request_is_enforced_without_cache(guarded_chat, monkeypatch, stage, outcome):
    client, log, cache, save, _ = guarded_chat
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    guard = AsyncMock(return_value=(False, "Blocked")) if outcome == "rejected" else AsyncMock(side_effect=GuardrailUnavailableError(stage, "timeout"))
    monkeypatch.setattr(routes, f"check_{stage}_guardrails", guard)
    response = post(client, guardrail_mode="shadow")
    assert response.status_code == (503 if outcome == "error" else 200)
    assert "Original answer" not in response.text
    saved = log.await_args.kwargs
    assert saved["request_status"] == ("technical_error" if outcome == "error" else f"blocked_{stage}")
    state = saved["guardrail_state"]
    assert state["mode"] == "enforce"
    assert state["status"] == outcome
    assert state[f"{stage}_safe"] is (False if outcome == "rejected" else None)
    assert state["stages"][stage]["status"] == outcome
    cache.assert_not_awaited()
    save.assert_not_awaited()


def test_server_enforce_cannot_be_disabled_and_rejection_is_not_error(guarded_chat, monkeypatch):
    client, log, *_ = guarded_chat
    monkeypatch.setattr(routes.settings, "PUBLIC_GUARDRAIL_MODE", "enforce")
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(False, "Rejected")))
    assert post(client, guardrail_mode="off").status_code == 200
    saved = log.await_args.kwargs
    assert saved["request_status"] == "blocked_input"
    assert not saved.get("technical_error")
    assert saved["guardrail_state"]["mode"] == "enforce"
    assert saved["guardrail_state"]["status"] == "rejected"
    assert saved["guardrail_state"]["output_safe"] is None


def test_success_distinguishes_both_executed_stages(guarded_chat, monkeypatch):
    client, log, *_ = guarded_chat
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    assert post(client, nemo_enabled="true").status_code == 200
    state = log.await_args.kwargs["guardrail_state"]
    assert state["status"] == "passed"
    assert state["requested"] is state["executed"] is True
    assert {stage["status"] for stage in state["stages"].values()} == {"passed"}


@pytest.mark.parametrize("generation_status", ["no_contexts", "authentication_failed"])
def test_missing_or_failed_generation_does_not_claim_output_safe(guarded_chat, monkeypatch, generation_status):
    client, log, _, _, rag = guarded_chat
    rag.return_value = ("Cannot answer", [], {"generation_status": generation_status})
    monkeypatch.setattr(routes, "check_input_guardrails", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(routes, "check_output_guardrails", AsyncMock(return_value=(True, "")))
    assert post(client, nemo_enabled="true").status_code == (200 if generation_status == "no_contexts" else 503)
    state = log.await_args.kwargs["guardrail_state"]
    assert state["input_safe"] is True
    assert state["output_safe"] is (True if generation_status == "no_contexts" else None)
    assert state["stages"]["output"]["status"] == ("passed" if generation_status == "no_contexts" else "not_run")


@pytest.mark.parametrize("reason", ["Bearer private", "private"])
def test_presenter_does_not_upgrade_legacy_or_error_safety(reason):
    legacy = build_public_retrieval_trace({"safety_status": {"input_safe": True, "output_safe": True}})
    assert legacy["guardrail_state"]["status"] == "unobserved"
    assert legacy["guardrail_state"]["input_safe"] is None
    trace = build_public_retrieval_trace({"guardrail_state": {
        "mode": "enforce", "requested": True, "executed": True, "status": "error",
        "input_safe": True, "output_safe": True, "secret": "private",
        "stages": {"input": {"status": "error", "safe": True, "error": {"type": "GuardrailUnavailableError", "stage": "input", "reason": reason, "message": "private"}}},
    }})
    state = trace["guardrail_state"]
    assert state["input_safe"] is None
    assert state["output_safe"] is None
    assert "private" not in str(state)


@pytest.mark.parametrize("stage", [{"status": "passed", "safe": None}, {"status": [], "safe": True}])
def test_presenter_requires_explicit_assessed_stage(stage):
    state = build_public_retrieval_trace({"guardrail_state": {
        "mode": "enforce", "executed": True, "stages": {"input": stage},
    }})["guardrail_state"]
    assert state["input_safe"] is None
    assert state["stages"]["input"]["status"] == "not_run"


def test_public_off_state_never_claims_execution():
    state = build_public_retrieval_trace({"guardrail_state": {
        "mode": "off", "requested": True, "executed": True,
        "stages": {"input": {"status": "passed", "safe": True}},
    }})["guardrail_state"]
    assert state["requested"] is state["executed"] is False
    assert state["input_safe"] is None


@pytest.mark.parametrize("executed", [False, None, "true"])
def test_public_stage_pass_requires_observed_execution(executed):
    state = build_public_retrieval_trace({"guardrail_state": {
        "mode": "enforce", "requested": True, "executed": executed, "status": "passed",
        "stages": {name: {"status": "passed", "safe": True} for name in ("input", "output")},
    }})["guardrail_state"]
    assert state["status"] == "unobserved"
    assert state["input_safe"] is state["output_safe"] is None
    assert {stage["status"] for stage in state["stages"].values()} == {"not_run"}
