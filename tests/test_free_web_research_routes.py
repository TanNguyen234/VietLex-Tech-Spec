from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


RUN_ID = "7f92d429-5982-4b71-8d0d-f90b1e44ca10"
CSRF = "c" * 64
QUESTION = "Quy định tiền lương khi thử việc"


def _readable_source() -> dict:
    return {
        "url": "https://vanban.chinhphu.vn/?docid=123",
        "title": "Văn bản thử nghiệm",
        "text": "Nội dung nguồn thử nghiệm, không phải tư vấn pháp lý.",
        "sha256": "a" * 64,
        "document_sha256": "b" * 64,
        "snapshot_key": "test-snapshot-1",
        "snapshot_timestamp": "2026-10-17T00:00:00+00:00",
        "retrieved_at": "2026-10-17T00:00:00+00:00",
        "method": "visible_html_text",
    }


class FakeResearchDatabase:
    """Small persistence-boundary fake; route and research DB functions stay real."""

    def __init__(self):
        self.workspaces = {
            "w-1": {
                "_id": "w-1",
                "workspace_id": "w-1",
                "client_id": "legacy",
                "user_id": "verified-user",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
                "analyses": [],
                "evidence": [],
                "documents": [],
            }
        }
        self.runs: dict[tuple[str, str | None, str], dict] = {}
        self.checkpoint_calls: list[tuple[str, dict]] = []
        self.checkpoint_attempts = 0
        self.workspace_reads: list[tuple[str, str, str | None]] = []
        self.begin_calls: list[tuple[str, str, str | None, dict]] = []
        self.replay_calls: list[tuple[str, str, str | None, str | None]] = []
        self.cancel_calls: list[tuple[str, str, str, str | None]] = []
        self.stream_calls: list[dict] = []
        self.checkpoint_delay_call: int | None = None
        self.checkpoint_delay_seconds = 0.0

    async def get_workspace(self, workspace_id, client_id, *, user_id=None):
        self.workspace_reads.append((workspace_id, client_id, user_id))
        workspace = self.workspaces.get(workspace_id)
        if workspace is None or workspace["expires_at"] <= datetime.now(timezone.utc):
            return None
        if user_id:
            if workspace.get("user_id") != user_id:
                return None
        elif workspace.get("user_id") is not None or workspace.get("client_id") != client_id:
            return None
        return deepcopy(workspace)

    def _run_key(self, workspace_id, client_id, user_id, run_id):
        return workspace_id, user_id or client_id, run_id

    async def begin(self, workspace_id, analysis, client_id, *, user_id=None):
        self.begin_calls.append((workspace_id, client_id, user_id, deepcopy(analysis)))
        workspace = await self.get_workspace(workspace_id, client_id, user_id=user_id)
        if workspace is None:
            return {"outcome": "not_found", "analysis": None}

        run_id = analysis["analysis_id"]
        key = self._run_key(workspace_id, client_id, user_id, run_id)
        existing = self.runs.get(key)
        if existing is not None:
            if existing.get("request_sha256") != analysis.get("request_sha256"):
                return {"outcome": "mismatch", "analysis": deepcopy(existing)}
            if existing.get("status") == "running":
                return {"outcome": "active", "analysis": deepcopy(existing)}
            return {"outcome": "replay", "analysis": deepcopy(existing)}

        for (saved_workspace, saved_owner, _), saved in self.runs.items():
            if (
                saved_workspace == workspace_id
                and saved_owner == (user_id or client_id)
                and saved.get("research_mode") == "free_web_research"
                and saved.get("status") == "running"
                and saved.get("lease_expires_at")
                and saved["lease_expires_at"] > datetime.now(timezone.utc)
            ):
                return {"outcome": "active", "analysis": deepcopy(saved)}

        stored = {
            **deepcopy(analysis),
            "kind": "trusted_sources",
            "research_mode": "free_web_research",
            "status": "running",
            "created_at": datetime.now(timezone.utc),
        }
        self.runs[key] = stored
        self._sync_analysis(workspace_id, user_id or client_id, run_id, stored)
        return {"outcome": "started", "analysis": deepcopy(stored)}

    async def checkpoint(self, workspace_id, run_id, state, client_id, *, user_id=None):
        self.checkpoint_attempts += 1
        call_number = self.checkpoint_attempts
        if call_number == self.checkpoint_delay_call:
            await asyncio.sleep(self.checkpoint_delay_seconds)
        key = self._run_key(workspace_id, client_id, user_id, run_id)
        current = self.runs.get(key)
        if current is None:
            return False
        saved = {
            **deepcopy(current),
            **deepcopy(state),
            "analysis_id": run_id,
            "research_mode": "free_web_research",
        }
        self.runs[key] = saved
        self._sync_analysis(workspace_id, user_id or client_id, run_id, saved)
        self.checkpoint_calls.append((run_id, deepcopy(saved)))
        return True

    async def replay(self, workspace_id, run_id, request_sha256, client_id, *, user_id=None):
        self.replay_calls.append((workspace_id, run_id, client_id, user_id))
        workspace = await self.get_workspace(workspace_id, client_id, user_id=user_id)
        if workspace is None:
            return {"outcome": "not_found", "analysis": None}
        key = self._run_key(workspace_id, client_id, user_id, run_id)
        saved = self.runs.get(key)
        if saved is None:
            return {"outcome": "not_found", "analysis": None}
        if request_sha256 is not None and request_sha256 != saved.get("request_sha256"):
            return {"outcome": "mismatch", "analysis": deepcopy(saved)}
        if saved.get("status") == "running":
            return {"outcome": "active", "analysis": deepcopy(saved)}
        return {"outcome": "replay", "analysis": deepcopy(saved)}

    async def cancel(self, workspace_id, run_id, client_id, *, user_id=None):
        self.cancel_calls.append((workspace_id, run_id, client_id, user_id))
        workspace = await self.get_workspace(workspace_id, client_id, user_id=user_id)
        if workspace is None:
            return {"outcome": "not_found", "status": None, "source_count": 0}
        key = self._run_key(workspace_id, client_id, user_id, run_id)
        saved = self.runs.get(key)
        if saved is None:
            return {"outcome": "not_found", "status": None, "source_count": 0}
        if saved.get("status") != "running":
            terminal = (saved.get("result") or {}).get("terminal") or {}
            if (
                saved.get("status") in {"partial", "cancelled"}
                and terminal.get("error_kind") == "user_cancelled"
            ):
                return {
                    "outcome": "cancelled",
                    "status": saved["status"],
                    "source_count": terminal.get("source_count", 0),
                }
            return {
                "outcome": "not_running",
                "status": saved.get("status"),
                "source_count": len((saved.get("result") or {}).get("sources") or []),
            }
        source_count = len((saved.get("result") or {}).get("sources") or [])
        status = "partial" if source_count else "cancelled"
        terminal = {
            "type": "terminal",
            "status": status,
            "analysis_id": run_id,
            "source_count": source_count,
            "error_kind": "user_cancelled",
        }
        saved["status"] = status
        saved["lease_expires_at"] = None
        saved["completed_at"] = datetime.now(timezone.utc)
        saved.setdefault("result", {})["status"] = status
        saved["result"]["terminal"] = {key: value for key, value in terminal.items() if key != "type"}
        saved["result"].setdefault("events", []).append(terminal)
        self._sync_analysis(workspace_id, user_id or client_id, run_id, saved)
        return {"outcome": "cancelled", "status": status, "source_count": source_count}

    def _sync_analysis(self, workspace_id, owner_id, run_id, saved):
        workspace = self.workspaces[workspace_id]
        if workspace.get("user_id") != owner_id and workspace.get("client_id") != owner_id:
            return
        analyses = workspace.setdefault("analyses", [])
        for index, current in enumerate(analyses):
            if current.get("analysis_id") == run_id:
                analyses[index] = deepcopy(saved)
                break
        else:
            analyses.append(deepcopy(saved))

    def key_for(self, run_id=RUN_ID, *, workspace_id="w-1", owner="verified-user"):
        return workspace_id, owner, run_id


def _enabled_settings(**overrides):
    values = {
        "APP_ENV": "test",
        "FREE_WEB_RESEARCH_ENABLED": True,
        "OFFICIAL_WEB_RESEARCH_ENABLED": True,
        "FREE_WEB_RESEARCH_PRODUCTION_LIMIT_VERIFIED": False,
        "FREE_WEB_RESEARCH_TOTAL_BUDGET_SECONDS": 5.0,
        "FREE_WEB_RESEARCH_SAVE_BUDGET_SECONDS": 1.0,
        "FREE_WEB_RESEARCH_RATE_LIMIT": "100/minute",
        "SESSION_RATE_LIMIT": "100/minute",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def harness(monkeypatch):
    import app.api.free_web_research_routes as routes
    import app.api.workspace_routes as workspace_routes

    store = FakeResearchDatabase()
    settings = _enabled_settings()
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "build_free_web_queries", lambda question: ["official " + question])
    monkeypatch.setattr(routes, "begin_free_research_run", store.begin)
    monkeypatch.setattr(routes, "checkpoint_free_research_run", store.checkpoint)
    monkeypatch.setattr(routes, "replay_free_research_run", store.replay)
    monkeypatch.setattr(routes, "cancel_free_research_run", store.cancel, raising=False)
    monkeypatch.setattr(workspace_routes, "get_workspace", store.get_workspace)

    async def default_stream(question, **kwargs):
        store.stream_calls.append({"question": question, **kwargs})
        yield {"type": "started", "status": "running", "query_count": 1}
        yield {"type": "query", "query": "official law", "result_count": 1}
        yield {"type": "source", "status": "readable", "source": _readable_source()}
        yield {
            "type": "terminal",
            "status": "complete",
            "source_count": 1,
        }

    monkeypatch.setattr(routes, "stream_free_web_research", default_stream)

    app = FastAPI()
    app.state.limiter = routes.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(routes.router)
    app.dependency_overrides[routes.optional_user] = lambda: {
        "_id": "verified-user",
        "status": "active",
        "email_verified": True,
    }
    routes.limiter._storage.reset()
    client = TestClient(app)
    client.cookies.set("csrf_token", CSRF)
    result = SimpleNamespace(
        app=app,
        client=client,
        routes=routes,
        settings=settings,
        store=store,
        stream=default_stream,
    )
    yield result
    client.close()
    routes.limiter._storage.reset()


def _post(client, *, question=QUESTION, run_id=RUN_ID, refresh="false", csrf=CSRF):
    data = {"question": question, "run_id": run_id, "refresh": refresh}
    if csrf is not None:
        data["csrf_token"] = csrf
    return client.post("/workspaces/w-1/research/read", data=data)


def _events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _reset_rate_limit(harness):
    harness.routes.limiter._storage.reset()


def test_post_uses_real_csrf_owner_scope_and_no_store_headers(harness):
    denied = _post(harness.client, csrf="wrong-token")
    assert denied.status_code == 403
    assert harness.store.workspace_reads == []

    response = _post(harness.client)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert [event["type"] for event in _events(response)] == [
        "started", "query", "source", "terminal"
    ]
    assert harness.store.workspace_reads[0] == ("w-1", "legacy", "verified-user")
    assert harness.store.begin_calls[0][1:3] == ("legacy", "verified-user")
    assert harness.store.checkpoint_calls


def test_cancel_requires_csrf_and_owner_and_is_independent_of_research_gate(harness):
    harness.store.runs[harness.store.key_for()] = {
        "analysis_id": RUN_ID,
        "research_mode": "free_web_research",
        "status": "running",
        "lease_expires_at": datetime.now(timezone.utc) + timedelta(minutes=2),
        "result": {"sources": [_readable_source()], "events": []},
    }
    harness.settings.FREE_WEB_RESEARCH_ENABLED = False

    denied = harness.client.post(
        f"/workspaces/w-1/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": "wrong-token"},
    )
    assert denied.status_code == 403
    assert harness.store.cancel_calls == []

    response = harness.client.post(
        f"/workspaces/w-1/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": CSRF},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "outcome": "cancelled",
        "status": "partial",
        "source_count": 1,
    }
    retry = harness.client.post(
        f"/workspaces/w-1/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": CSRF},
    )
    assert retry.status_code == 200
    assert retry.json() == response.json()
    assert harness.store.cancel_calls == [
        ("w-1", RUN_ID, "legacy", "verified-user"),
        ("w-1", RUN_ID, "legacy", "verified-user"),
    ]
    saved = harness.store.runs[harness.store.key_for()]
    assert saved["status"] == "partial"
    assert saved["lease_expires_at"] is None
    assert saved["result"]["sources"] == [_readable_source()]
    assert saved["result"]["terminal"]["error_kind"] == "user_cancelled"
    assert len(saved["result"]["events"]) == 1
    assert harness.store.begin_calls == []
    assert harness.store.replay_calls == []
    assert harness.store.stream_calls == []


def test_cancel_does_not_disclose_foreign_workspace_or_run(harness):
    response = harness.client.post(
        f"/workspaces/foreign/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": CSRF},
    )
    assert response.status_code == 404
    assert harness.store.cancel_calls == []

    missing = harness.client.post(
        f"/workspaces/w-1/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": CSRF},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "research_run_not_found"


def test_cancel_retry_keeps_conflict_for_a_natural_terminal_run(harness):
    harness.store.runs[harness.store.key_for()] = {
        "analysis_id": RUN_ID,
        "research_mode": "free_web_research",
        "status": "complete",
        "result": {
            "sources": [_readable_source()],
            "terminal": {"status": "complete", "source_count": 1, "error_kind": "complete"},
        },
    }

    response = harness.client.post(
        f"/workspaces/w-1/research/runs/{RUN_ID}/cancel",
        data={"csrf_token": CSRF},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "research_run_not_running",
        "status": "complete",
    }


def test_production_feature_gate_requires_explicit_limit_attestation(harness):
    harness.settings.APP_ENV = "production"
    harness.settings.FREE_WEB_RESEARCH_PRODUCTION_LIMIT_VERIFIED = False

    response = _post(harness.client)

    assert response.status_code == 503
    assert response.json() == {"detail": "free_web_research_unavailable"}
    assert harness.store.workspace_reads == []
    assert harness.store.begin_calls == []
    assert harness.store.stream_calls == []


def test_same_payload_replays_but_question_or_refresh_mismatch_is_422(harness):
    first = _post(harness.client, question="  Quy định   tiền lương khi thử việc  ")
    _reset_rate_limit(harness)
    replay = _post(harness.client, question=QUESTION)

    assert first.status_code == replay.status_code == 200
    assert _events(replay)[-1]["replayed"] is True
    assert len(harness.store.stream_calls) == 1
    assert harness.routes._request_hash(QUESTION, False) != harness.routes._request_hash(
        QUESTION, True
    )

    _reset_rate_limit(harness)
    question_mismatch = _post(harness.client, question="Quy định về nghỉ phép")
    _reset_rate_limit(harness)
    refresh_mismatch = _post(harness.client, refresh="true")
    assert question_mismatch.status_code == 422
    assert question_mismatch.json()["detail"] == "run_id_payload_mismatch"
    assert refresh_mismatch.status_code == 422
    assert refresh_mismatch.json()["detail"] == "run_id_payload_mismatch"
    assert len(harness.store.stream_calls) == 1


def test_active_workspace_run_returns_conflict(harness):
    active_id = "a5d62ccd-579c-4430-bbb7-1d6ed0bc6e57"
    now = datetime.now(timezone.utc)
    harness.store.runs[harness.store.key_for(active_id)] = {
        "analysis_id": active_id,
        "research_mode": "free_web_research",
        "status": "running",
        "lease_expires_at": now + timedelta(minutes=1),
        "result": {"events": [], "sources": []},
    }

    response = _post(harness.client)

    assert response.status_code == 409
    assert response.json()["detail"] == "research_run_in_progress"
    assert harness.store.stream_calls == []


@pytest.mark.parametrize("workspace_state", ["expired", "other_owner"])
def test_expired_and_other_owner_workspaces_are_hidden_as_not_found(harness, workspace_state):
    workspace = harness.store.workspaces["w-1"]
    if workspace_state == "expired":
        workspace["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    else:
        workspace["user_id"] = "someone-else"

    response = _post(harness.client)

    assert response.status_code == 404
    assert harness.store.begin_calls == []
    assert harness.store.stream_calls == []


def test_status_is_owner_scoped_and_never_cacheable(harness):
    created = _post(harness.client)
    assert created.status_code == 200
    saved = harness.store.runs[harness.store.key_for()]
    assert saved["status"] == "complete"

    response = harness.client.get(f"/workspaces/w-1/research/runs/{RUN_ID}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["outcome"] == "replay"
    assert response.json()["analysis"]["analysis_id"] == RUN_ID
    assert harness.store.replay_calls[-1] == ("w-1", RUN_ID, "legacy", "verified-user")

    harness.app.dependency_overrides[harness.routes.optional_user] = lambda: {
        "_id": "another-user",
        "status": "active",
        "email_verified": True,
    }
    _reset_rate_limit(harness)
    replay_count = len(harness.store.replay_calls)
    hidden = harness.client.get(f"/workspaces/w-1/research/runs/{RUN_ID}")
    assert hidden.status_code == 404
    assert harness.store.workspace_reads[-1] == ("w-1", "legacy", "another-user")
    assert len(harness.store.replay_calls) == replay_count


def test_blank_question_is_rejected_before_run_claim(harness):
    response = _post(harness.client, question="   \t  ")

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_research_question"
    assert harness.store.begin_calls == []
    assert harness.store.stream_calls == []


def test_events_are_sent_only_after_their_checkpoint_is_saved(harness):
    trace = []

    async def run_request():
        raw_body = urlencode(
            {
                "question": QUESTION,
                "run_id": RUN_ID,
                "refresh": "false",
                "csrf_token": CSRF,
            }
        ).encode()
        request_pending = True

        async def receive():
            nonlocal request_pending
            if request_pending:
                request_pending = False
                return {
                    "type": "http.request",
                    "body": raw_body,
                    "more_body": False,
                }
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                event = json.loads(message["body"])
                if event["type"] in {"query", "source", "terminal"}:
                    saved = harness.store.runs[harness.store.key_for()]
                    saved_types = [item.get("type") for item in saved["result"]["events"]]
                    assert event["type"] in saved_types
                    trace.append(("send", event["type"]))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/workspaces/w-1/research/read",
            "raw_path": b"/workspaces/w-1/research/read",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(raw_body)).encode()),
                (b"cookie", f"csrf_token={CSRF}".encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        await harness.app(scope, receive, send)

    monkeypatch_checkpoint = harness.store.checkpoint

    async def recording_checkpoint(*args, **kwargs):
        saved = await monkeypatch_checkpoint(*args, **kwargs)
        if saved:
            state = args[2]
            event_types = [item.get("type") for item in (state.get("result") or {}).get("events", [])]
            trace.append(("checkpoint", event_types[-1] if event_types else None))
        return saved

    harness.routes.checkpoint_free_research_run = recording_checkpoint
    asyncio.run(run_request())

    for event_type in ("query", "source", "terminal"):
        assert trace.index(("checkpoint", event_type)) < trace.index(("send", event_type))


def test_running_checkpoints_keep_the_original_absolute_lease_deadline(harness, monkeypatch):
    original_stream = harness.routes.stream_free_web_research

    async def delayed_stream(question, **kwargs):
        await asyncio.sleep(0.05)
        async for event in original_stream(question, **kwargs):
            yield event

    monkeypatch.setattr(harness.routes, "stream_free_web_research", delayed_stream)

    response = _post(harness.client)

    assert response.status_code == 200
    original_deadline = harness.store.begin_calls[0][3]["lease_expires_at"]
    running_checkpoints = [
        saved
        for _, saved in harness.store.checkpoint_calls
        if saved.get("status") == "running"
    ]
    assert running_checkpoints
    assert all(saved["lease_expires_at"] == original_deadline for saved in running_checkpoints)


def test_started_event_is_atomic_in_claim_without_a_double_save_lock(harness, monkeypatch):
    checkpoint = harness.store.checkpoint
    failed_save_paths = []

    async def fail_start_and_cleanup(*args, **kwargs):
        state = args[2]
        result = state.get("result") or {}
        events = result.get("events") or []
        if len(events) == 1 and events[0].get("type") == "started":
            failed_save_paths.append("started")
            return False
        terminal = result.get("terminal") or {}
        if terminal.get("error_kind") == "research_start_checkpoint_failed":
            failed_save_paths.append("terminal_cleanup")
            return False
        return await checkpoint(*args, **kwargs)

    monkeypatch.setattr(harness.routes, "checkpoint_free_research_run", fail_start_and_cleanup)

    response = _post(harness.client)

    assert response.status_code == 200
    claimed = harness.store.begin_calls[0][3]
    assert claimed["result"]["events"][0]["type"] == "started"
    assert failed_save_paths == []
    saved = harness.store.runs[harness.store.key_for()]
    assert saved["status"] == "complete"
    assert saved["lease_expires_at"] is None
    assert saved["result"]["events"][0]["type"] == "started"
    assert len(harness.store.stream_calls) == 1


def test_checkpoint_timeout_emits_typed_terminal_instead_of_silent_eof(harness):
    harness.settings.FREE_WEB_RESEARCH_SAVE_BUDGET_SECONDS = 0.2
    harness.store.checkpoint_delay_call = 1
    harness.store.checkpoint_delay_seconds = 0.5

    response = _post(harness.client)

    assert response.status_code == 200
    events = _events(response)
    assert events[-1]["type"] == "terminal"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error_kind"] == "research_save_timeout"
    assert type(events[-1]["persisted"]) is bool
    saved_terminal = harness.store.runs[harness.store.key_for()]["result"].get("terminal")
    if events[-1]["persisted"]:
        assert saved_terminal["error_kind"] == "research_save_timeout"
    else:
        assert saved_terminal is None


def test_checkpoint_exception_emits_sanitized_non_durable_terminal(harness, monkeypatch):
    async def broken_checkpoint(*args, **kwargs):
        raise RuntimeError('private connection details must not escape')

    monkeypatch.setattr(harness.routes, 'checkpoint_free_research_run', broken_checkpoint)
    response = _post(harness.client)
    events = [json.loads(line) for line in response.text.splitlines() if line]
    terminal = events[-1]
    assert terminal['type'] == 'terminal'
    assert terminal['error_kind'] == 'research_checkpoint_unavailable'
    assert terminal['persisted'] is False
    assert 'private connection' not in response.text


def test_failed_terminal_checkpoint_still_reports_transient_failure(harness, monkeypatch):
    async def no_checkpoint(*args, **kwargs):
        return False
    monkeypatch.setattr(harness.routes, 'checkpoint_free_research_run', no_checkpoint)
    response = _post(harness.client)
    assert response.status_code == 200
    terminal = _events(response)[-1]
    assert terminal['type'] == 'terminal'
    assert terminal['error_kind'] == 'research_save_timeout'
    assert terminal['persisted'] is False


def test_durable_cancellation_wins_over_inflight_source_event(harness, monkeypatch):
    async def cancel_then_emit(question, **kwargs):
        await harness.store.cancel('w-1', RUN_ID, 'legacy', user_id='verified-user')
        yield {'type': 'source', 'status': 'readable', 'source': _readable_source()}
    monkeypatch.setattr(harness.routes, 'stream_free_web_research', cancel_then_emit)
    async def cancelled_checkpoint(*args, **kwargs):
        return False  # Real DB checkpoint matches only status=running, not cancelled.
    monkeypatch.setattr(harness.routes, 'checkpoint_free_research_run', cancelled_checkpoint)
    response = _post(harness.client)
    terminal = _events(response)[-1]
    assert terminal['type'] == 'terminal'
    assert terminal['error_kind'] == 'user_cancelled'
    assert terminal['persisted'] is True
    assert terminal['status'] == 'cancelled'


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError('private detail')])
def test_durable_cancellation_wins_over_terminal_error(harness, monkeypatch, error):
    async def cancel_then_fail(question, **kwargs):
        await harness.store.cancel('w-1', RUN_ID, 'legacy', user_id='verified-user')
        raise error
        yield  # Keep the real provider async-generator boundary.

    async def cancelled_checkpoint(*args, **kwargs):
        return False

    monkeypatch.setattr(harness.routes, 'stream_free_web_research', cancel_then_fail)
    monkeypatch.setattr(harness.routes, 'checkpoint_free_research_run', cancelled_checkpoint)
    terminal = _events(_post(harness.client))[-1]
    assert terminal['error_kind'] == 'user_cancelled'
    assert terminal['persisted'] is True
    assert terminal['status'] == 'cancelled'


def test_provider_exception_yields_typed_partial_without_raw_exception_text(harness, monkeypatch):
    async def failing_stream(question, **kwargs):
        harness.store.stream_calls.append({"question": question, **kwargs})
        yield {"type": "source", "status": "readable", "source": _readable_source()}
        raise RuntimeError("private raw provider body and credential=do-not-leak")

    monkeypatch.setattr(harness.routes, "stream_free_web_research", failing_stream)

    response = _post(harness.client)

    events = _events(response)
    assert response.status_code == 200
    assert events[-1]["type"] == "terminal"
    assert events[-1]["status"] == "partial"
    assert events[-1]["source_count"] == 1
    assert events[-1]["error_kind"] == "RuntimeError"
    assert "private raw provider body" not in response.text
    assert "do-not-leak" not in response.text


def test_production_demo_admission_uses_free_research_quota_not_ai_quota(harness, monkeypatch):
    import app.services.reviewer_demo as demo

    settings = _enabled_settings(
        APP_ENV="production",
        FREE_WEB_RESEARCH_PRODUCTION_LIMIT_VERIFIED=True,
        REVIEWER_DEMO_MODE=True,
        AUTH_COOKIE_NAME="auth",
        DEMO_AI_DAILY_LIMIT=7,
        DEMO_AI_GLOBAL_DAILY_LIMIT=70,
    )
    harness.settings.APP_ENV = settings.APP_ENV
    harness.settings.FREE_WEB_RESEARCH_PRODUCTION_LIMIT_VERIFIED = True
    monkeypatch.setattr(
        demo,
        "resolve_auth_session",
        lambda _: asyncio.sleep(0, result={
            "_id": "verified-user",
            "status": "active",
            "email_verified": True,
        }),
    )
    reservations = []

    async def reserve(subject, category, personal, total, *, minute=False):
        reservations.append((subject, category, personal, total, minute))
        return True

    monkeypatch.setattr(demo, "reserve_demo_budget", reserve)
    harness.app.add_middleware(demo.ReviewerDemoMiddleware, settings=settings)
    harness.client.cookies.set("auth", "test-session")

    response = _post(harness.client)

    assert response.status_code == 200
    assert len(reservations) == 2
    assert [call[1] for call in reservations] == ["free_research", "free_research"]
    assert [call[2:] for call in reservations] == [(2, 60, True), (100, 1000, False)]


def test_asgi_disconnect_cancels_stream_children_and_persists_partial_run(harness, monkeypatch):
    disconnect = asyncio.Event()
    child_cancelled = asyncio.Event()

    async def stream_with_child(question, **kwargs):
        harness.store.stream_calls.append({"question": question, **kwargs})

        async def child_work():
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()

        async with asyncio.TaskGroup() as group:
            group.create_task(child_work())
            yield {"type": "query", "query": "official law", "result_count": 1}
            yield {"type": "source", "status": "readable", "source": _readable_source()}
            await asyncio.Event().wait()

    monkeypatch.setattr(harness.routes, "stream_free_web_research", stream_with_child)

    async def run_disconnect():
        raw_body = urlencode(
            {
                "question": QUESTION,
                "run_id": RUN_ID,
                "refresh": "false",
                "csrf_token": CSRF,
            }
        ).encode()
        request_pending = True
        sent_source = False

        async def receive():
            nonlocal request_pending
            if request_pending:
                request_pending = False
                return {
                    "type": "http.request",
                    "body": raw_body,
                    "more_body": False,
                }
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal sent_source
            if message["type"] == "http.response.body" and message.get("body"):
                event = json.loads(message["body"])
                if event.get("type") == "source":
                    sent_source = True
                    disconnect.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/workspaces/w-1/research/read",
            "raw_path": b"/workspaces/w-1/research/read",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(raw_body)).encode()),
                (b"cookie", f"csrf_token={CSRF}".encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        try:
            await asyncio.wait_for(harness.app(scope, receive, send), timeout=3.0)
        except BaseException as error:
            # A server may surface the cancelled response task; the disconnect is
            # still considered exercised only if the ASGI client saw the source.
            assert isinstance(error, (asyncio.CancelledError, ExceptionGroup))
        assert sent_source

    asyncio.run(run_disconnect())

    saved = harness.store.runs[harness.store.key_for()]
    assert child_cancelled.is_set()
    assert saved["status"] == "partial"
    assert saved["result"]["terminal"]["error_kind"] == "client_disconnected"
    assert saved["result"]["terminal"]["source_count"] == 1


def test_disconnected_checkpoint_is_shielded_but_has_a_hard_timeout(monkeypatch):
    from app.api import free_web_research_routes as routes

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowSaveBudget:
        async def checkpoint(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(5)
            finally:
                cancelled.set()

    async def run():
        task = asyncio.create_task(
            routes._persist_disconnected_run(
                "w-1", RUN_ID, {"status": "running", "result": {"sources": []}},
                "legacy", "verified-user", SlowSaveBudget(),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=0.2)
        await asyncio.wait_for(task, timeout=2.5)
        assert task.done()

    asyncio.run(run())
    assert started.is_set()
    assert cancelled.is_set()
