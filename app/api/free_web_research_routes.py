"""Owner-scoped NDJSON free research using official discovery and reading only."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import optional_user, verify_csrf
from app.api.workspace_routes import _owned_workspace, _validate_id
from app.config import get_settings
from app.rate_limit import limiter
from app.research_database import (
    begin_free_research_run,
    cancel_free_research_run,
    checkpoint_free_research_run,
    replay_free_research_run,
)
from app.services.free_web_research import (
    build_free_web_queries,
    stream_free_web_research,
)


router = APIRouter()
_RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _research_enabled(settings) -> bool:
    return bool(
        getattr(settings, "FREE_WEB_RESEARCH_ENABLED", False)
        and getattr(settings, "OFFICIAL_WEB_RESEARCH_ENABLED", False)
        and (
            getattr(settings, "APP_ENV", "development") != "production"
            or getattr(settings, "FREE_WEB_RESEARCH_PRODUCTION_LIMIT_VERIFIED", False)
        )
    )


def _request_hash(question: str, refresh: bool) -> str:
    normalized = " ".join(question.split())
    payload = json.dumps([normalized, bool(refresh)], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=_json_default) + "\n").encode("utf-8")


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported NDJSON value: {type(value).__name__}")


def _event_summary(event: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    summary = {key: value for key, value in event.items() if key != "source"}
    if event.get("type") == "source" and event.get("status") == "readable":
        summary["source_index"] = len(result.get("sources", [])) - 1
        source = event.get("source") or {}
        summary["snapshot_key"] = source.get("snapshot_key")
    return summary


def _apply_event(state: dict[str, Any], event: dict[str, Any], run_id: str) -> dict[str, Any]:
    updated = {**state}
    result = {**(state.get("result") or {})}
    event_type = event.get("type")
    if event_type == "started":
        result["events"] = [*(result.get("events") or []), _event_summary(event, result)]
    elif event_type == "query":
        result["queries"] = [*(result.get("queries") or []), {key: value for key, value in event.items() if key != "type"}]
        result["events"] = [*(result.get("events") or []), _event_summary(event, result)]
    elif event_type == "source":
        if event.get("status") == "readable":
            result["sources"] = [*(result.get("sources") or []), event["source"]]
        else:
            result["source_errors"] = [*(result.get("source_errors") or []), {key: value for key, value in event.items() if key != "type"}]
        result["events"] = [*(result.get("events") or []), _event_summary(event, result)]
    elif event_type == "terminal":
        result["terminal"] = {key: value for key, value in event.items() if key != "type"}
        result["status"] = event.get("status", "failed")
        result["events"] = [*(result.get("events") or []), _event_summary(event, result)]
        updated["status"] = event.get("status", "failed")
        updated["completed_at"] = datetime.now(timezone.utc)
        updated["lease_expires_at"] = None
        if event.get("status") == "complete":
            updated["provider"] = "government_official_federation"
        updated["analysis_id"] = run_id
    updated["result"] = result
    return updated


class _SaveBudget:
    def __init__(self, seconds: float, used: float = 0.0):
        self.seconds = min(15.0, max(0.0, seconds))
        self.used = min(self.seconds, max(0.0, used))
        self.failure_kind = "research_save_timeout"

    async def checkpoint(self, workspace_id, run_id, state, client_id, user_id, *, final=False):
        remaining = self.seconds - self.used - (0.0 if final else min(2.0, self.seconds / 4))
        if remaining <= 0:
            return False
        started = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(remaining):
                saved = await checkpoint_free_research_run(
                    workspace_id, run_id, state, client_id, user_id=user_id
                )
        except TimeoutError:
            saved = False
        except Exception:
            self.failure_kind = "research_checkpoint_unavailable"
            saved = False
        finally:
            self.used += asyncio.get_running_loop().time() - started
        return saved


def _replay_events(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    result = analysis.get("result") or {}
    sources = result.get("sources") or []
    events = []
    for event in result.get("events") or []:
        replay = dict(event)
        if replay.get("type") == "source" and replay.get("status") == "readable":
            index = replay.pop("source_index", None)
            replay.pop("snapshot_key", None)
            if isinstance(index, int) and 0 <= index < len(sources):
                replay["source"] = sources[index]
        events.append(replay)
    if not events or events[0].get("type") != "started":
        events.insert(0, {"type": "started", "status": "running", "query_count": len(result.get("queries") or [])})
    if not events or events[-1].get("type") != "terminal":
        events.append({
            "type": "terminal",
            "status": analysis.get("status", result.get("status", "interrupted")),
            "analysis_id": analysis.get("analysis_id"),
            "source_count": len(sources),
            "replayed": True,
        })
    else:
        events[-1].setdefault("analysis_id", analysis.get("analysis_id"))
        events[-1]["replayed"] = True
    return events


def _response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body():
        async with aclosing(events):
            async for event in events:
                yield _ndjson(event)

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _durable_terminal(workspace_id, run_id, client_id, user_id):
    try:
        async with asyncio.timeout(1.0):
            replay = await replay_free_research_run(
                workspace_id, run_id, None, client_id, user_id=user_id
            )
        durable = (replay or {}).get('analysis') or {}
        if durable.get('status') in {'cancelled', 'partial', 'complete', 'failed'}:
            return {**_replay_events(durable)[-1], 'persisted': True}
    except Exception:
        pass  # The caller emits its typed, explicitly non-durable terminal.
    return None


async def _final_terminal(terminal, persisted, workspace_id, run_id, client_id, user_id):
    if not persisted:
        durable = await _durable_terminal(workspace_id, run_id, client_id, user_id)
        if durable is not None:
            return durable
    return {**terminal, 'persisted': bool(persisted)}


async def _replay_stream(analysis: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    for event in _replay_events(analysis):
        yield event


async def _new_run_stream(
    *,
    workspace_id: str,
    run_id: str,
    question: str,
    client_id: str,
    user_id: str | None,
    initial_state: dict[str, Any],
    started_event: dict[str, Any],
    settings,
    remaining_total: float,
    lease_deadline: datetime,
    save_budget: _SaveBudget,
    owner_scope: str,
    cached_sources: list[dict[str, Any]],
    refresh: bool,
) -> AsyncIterator[dict[str, Any]]:
    state = initial_state
    try:
        # The atomic run claim already contains this event.
        yield started_event
        async with asyncio.timeout(max(0.0, remaining_total)):
            stream = stream_free_web_research(
                question,
                settings=settings,
                workspace_id=workspace_id,
                owner_scope=owner_scope,
                cached_sources=cached_sources,
                refresh=refresh,
            )
            async with aclosing(stream):
                async for event in stream:
                    if event.get("type") == "started":
                        continue
                    if event.get("type") == "terminal":
                        event = {**event, "analysis_id": run_id}
                    state = _apply_event(state, event, run_id)
                    state["updated_at"] = datetime.now(timezone.utc)
                    if state.get("status") == "running":
                        state["lease_expires_at"] = lease_deadline
                    if not await save_budget.checkpoint(
                        workspace_id, run_id, state, client_id, user_id,
                        final=event.get("type") == "terminal",
                    ):
                        # An owner cancellation atomically removes the running
                        # checkpoint target. Prefer that durable state to a
                        # newly invented save-timeout result for an in-flight read.
                        durable = await _durable_terminal(workspace_id, run_id, client_id, user_id)
                        if durable is not None:
                            yield durable
                            return
                        terminal = {
                            "type": "terminal",
                            "status": "partial" if (state.get("result") or {}).get("sources") else "failed",
                            "analysis_id": run_id,
                            "source_count": len((state.get("result") or {}).get("sources") or []),
                            "error_kind": save_budget.failure_kind,
                        }
                        terminal_state = _apply_event(state, terminal, run_id)
                        terminal_state["updated_at"] = datetime.now(timezone.utc)
                        persisted = await save_budget.checkpoint(
                            workspace_id, run_id, terminal_state, client_id, user_id, final=True
                        )
                        # Never silently end the response, and never claim a
                        # failed checkpoint is durable. A later GET is authoritative.
                        yield await _final_terminal(terminal, persisted, workspace_id, run_id, client_id, user_id)
                        return
                    # Each event is emitted only after its bounded state is durable.
                    yield event
                    if event.get("type") == "terminal":
                        return
    except asyncio.CancelledError:
        await _persist_disconnected_run(
            workspace_id, run_id, state, client_id, user_id, save_budget
        )
        raise
    except GeneratorExit:
        await _persist_disconnected_run(
            workspace_id, run_id, state, client_id, user_id, save_budget
        )
        raise
    except TimeoutError:
        current_sources = (state.get("result") or {}).get("sources") or []
        terminal = {
            "type": "terminal",
            "status": "partial" if current_sources else "failed",
            "analysis_id": run_id,
            "source_count": len(current_sources),
            "error_kind": "run_deadline",
        }
        state = _apply_event(state, terminal, run_id)
        state["updated_at"] = datetime.now(timezone.utc)
        persisted = await save_budget.checkpoint(workspace_id, run_id, state, client_id, user_id, final=True)
        yield await _final_terminal(terminal, persisted, workspace_id, run_id, client_id, user_id)
    except Exception as error:
        current_sources = (state.get("result") or {}).get("sources") or []
        terminal = {
            "type": "terminal",
            "status": "partial" if current_sources else "failed",
            "analysis_id": run_id,
            "source_count": len(current_sources),
            "error_kind": str(getattr(error, "kind", type(error).__name__))[:100],
        }
        state = _apply_event(state, terminal, run_id)
        state["updated_at"] = datetime.now(timezone.utc)
        persisted = await save_budget.checkpoint(workspace_id, run_id, state, client_id, user_id, final=True)
        yield await _final_terminal(terminal, persisted, workspace_id, run_id, client_id, user_id)


async def _persist_disconnected_run(workspace_id, run_id, state, client_id, user_id, save_budget):
    sources = (state.get("result") or {}).get("sources") or []
    terminal = {
        "type": "terminal",
        "status": "partial" if sources else "cancelled",
        "analysis_id": run_id,
        "source_count": len(sources),
        "error_kind": "client_disconnected",
    }
    state = _apply_event(state, terminal, run_id)
    state["updated_at"] = datetime.now(timezone.utc)
    try:
        checkpoint = asyncio.create_task(
            save_budget.checkpoint(
                workspace_id, run_id, state, client_id, user_id, final=True
            )
        )
        await asyncio.wait_for(asyncio.shield(checkpoint), timeout=2.0)
    except (Exception, asyncio.CancelledError):
        if "checkpoint" in locals() and not checkpoint.done():
            checkpoint.cancel()
            await asyncio.gather(checkpoint, return_exceptions=True)
        return


@router.post("/workspaces/{workspace_id}/research/read")
@limiter.limit(get_settings().FREE_WEB_RESEARCH_RATE_LIMIT)
async def free_web_research_read(
    request: Request,
    workspace_id: str,
    question: str = Form(..., min_length=1, max_length=2_000),
    run_id: str = Form(..., min_length=36, max_length=36),
    refresh: bool = Form(False),
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    settings = get_settings()
    if not _research_enabled(settings):
        raise HTTPException(status_code=503, detail="free_web_research_unavailable")
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="invalid_research_run_id")
    clean_question = " ".join(question.split())
    if not clean_question:
        raise HTTPException(status_code=422, detail="invalid_research_question")
    started_at = asyncio.get_running_loop().time()
    total_budget = min(
        180.0,
        float(getattr(settings, "FREE_WEB_RESEARCH_TOTAL_BUDGET_SECONDS", 180.0)),
    )
    save_seconds = min(
        15.0,
        float(getattr(settings, "FREE_WEB_RESEARCH_SAVE_BUDGET_SECONDS", 15.0)),
    )
    lease_expires = datetime.now(timezone.utc) + timedelta(seconds=total_budget)
    try:
        workspace, client_id, user_id = await _owned_workspace(
            request, workspace_id, current_user
        )
    except HTTPException:
        raise
    request_sha256 = _request_hash(clean_question, refresh)
    queries = build_free_web_queries(clean_question)
    if not queries:
        raise HTTPException(status_code=422, detail="invalid_research_question")
    started_event = {
        "type": "started",
        "status": "running",
        "analysis_id": run_id,
        "query_count": len(queries),
    }
    initial_analysis = {
        "analysis_id": run_id,
        "kind": "trusted_sources",
        "research_mode": "free_web_research",
        "request_sha256": request_sha256,
        "question": clean_question,
        "status": "running",
        "lease_expires_at": lease_expires,
        "provider": "government_official_federation",
        "model": None,
        "result": {
            "status": "running",
            "question": clean_question,
            "query_plan": queries,
            "queries": [],
            "sources": [],
            "source_errors": [],
            "events": [_event_summary(started_event, {})],
            "cache_scope": "owner_workspace",
            "refresh_requested": refresh,
        },
    }
    elapsed = asyncio.get_running_loop().time() - started_at
    cleanup_reserve = min(2.0, save_seconds / 4)
    begin_timeout = min(
        max(0.0, save_seconds - cleanup_reserve),
        max(0.0, total_budget - elapsed),
    )
    save_budget = _SaveBudget(save_seconds)
    save_started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(begin_timeout):
            claim = await begin_free_research_run(
                workspace_id, initial_analysis, client_id, user_id=user_id
            )
    except TimeoutError as error:
        raise HTTPException(status_code=503, detail="research_save_timeout") from error
    save_budget.used += asyncio.get_running_loop().time() - save_started
    outcome = claim.get("outcome")
    analysis = claim.get("analysis")
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="workspace_not_found")
    if outcome == "mismatch":
        raise HTTPException(status_code=422, detail="run_id_payload_mismatch")
    if outcome == "active":
        raise HTTPException(status_code=409, detail="research_run_in_progress")
    if outcome == "changed":
        raise HTTPException(status_code=409, detail="workspace_changed")
    if outcome == "size_limit":
        raise HTTPException(status_code=413, detail="workspace_storage_limit")
    if outcome == "replay":
        return _response(_replay_stream(analysis))
    if outcome != "started" or not analysis:
        raise HTTPException(status_code=503, detail="research_run_unavailable")

    initial_state = {
        key: value
        for key, value in analysis.items()
        if key not in {"created_at", "analysis_id", "research_mode"}
    }
    total_remaining = total_budget - (asyncio.get_running_loop().time() - started_at)
    cached_sources = [
        source
        for prior in reversed((workspace.get("analyses") or [])[-50:])
        if prior.get("research_mode") == "free_web_research"
        and prior.get("analysis_id") != run_id
        for source in ((prior.get("result") or {}).get("sources") or [])[:3]
    ]
    owner_scope = f"user:{user_id}" if user_id else f"client:{client_id}"
    return _response(
        _new_run_stream(
            workspace_id=workspace_id,
            run_id=run_id,
            question=clean_question,
            client_id=client_id,
            user_id=user_id,
            initial_state=initial_state,
            started_event=started_event,
            settings=settings,
            remaining_total=total_remaining,
            lease_deadline=lease_expires,
            save_budget=save_budget,
            owner_scope=owner_scope,
            cached_sources=cached_sources,
            refresh=refresh,
        )
    )


@router.get("/workspaces/{workspace_id}/research/runs/{run_id}")
@limiter.limit(get_settings().SESSION_RATE_LIMIT)
async def free_web_research_run_status(
    request: Request,
    workspace_id: str,
    run_id: str,
    current_user=Depends(optional_user),
):
    _validate_id(run_id, "research_run")
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    replay = await replay_free_research_run(
        workspace_id, run_id, None, client_id, user_id=user_id
    )
    if replay.get("outcome") == "not_found":
        raise HTTPException(status_code=404, detail="research_run_not_found")
    if replay.get("outcome") == "changed":
        raise HTTPException(status_code=409, detail="workspace_changed")
    return JSONResponse(
        jsonable_encoder({"analysis": replay.get("analysis"), "outcome": replay.get("outcome")}),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/workspaces/{workspace_id}/research/runs/{run_id}/cancel")
@limiter.limit(get_settings().SESSION_RATE_LIMIT)
async def free_web_research_cancel(
    request: Request,
    workspace_id: str,
    run_id: str,
    _csrf: str = Depends(verify_csrf),
    current_user=Depends(optional_user),
):
    if not _RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail="invalid_research_run_id")
    _workspace, client_id, user_id = await _owned_workspace(
        request, workspace_id, current_user
    )
    result = await cancel_free_research_run(
        workspace_id, run_id, client_id, user_id=user_id
    )
    if result["outcome"] == "not_found":
        raise HTTPException(status_code=404, detail="research_run_not_found")
    if result["outcome"] == "size_limit":
        raise HTTPException(status_code=413, detail="research_workspace_size_limit")
    if result["outcome"] == "not_running":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "research_run_not_running",
                "status": result.get("status"),
            },
        )
    return JSONResponse(
        jsonable_encoder({
            "outcome": "cancelled",
            "status": result["status"],
            "source_count": result["source_count"],
        }),
        headers={"Cache-Control": "no-store"},
    )
