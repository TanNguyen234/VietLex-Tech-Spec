from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_begin_free_research_run_is_owner_scoped_atomic_and_bounded(monkeypatch):
    from app import research_database as database

    collection = SimpleNamespace(
        find_one=AsyncCollectionResult({"analyses": []}),
        update_one=AsyncCollectionResult(SimpleNamespace(modified_count=1)),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.begin_free_research_run(
        "workspace-1",
        {
            "analysis_id": "run-1",
            "request_sha256": "a" * 64,
            "question": "Question",
            "result": {"queries": [], "sources": [], "events": []},
        },
        "owner-1",
        user_id="user-1",
    )

    assert result["outcome"] == "started"
    query, update = collection.update_one.await_args.args
    assert query["_id"] == "workspace-1"
    assert query["user_id"] == "user-1"
    assert query["expires_at"]["$gt"].tzinfo == timezone.utc
    assert query["analyses"]["$not"]["$elemMatch"]["status"] == "running"
    assert isinstance(update, list)
    appended = update[-1]["$set"]["analyses"]["$slice"]
    assert appended[-1] == -50
    assert appended[0]["$concatArrays"][1]["$literal"][0]["analysis_id"] == "run-1"
    assert "$push" not in str(update)
    assert "$expr" in query


@pytest.mark.asyncio
async def test_checkpoint_replaces_embedded_run_atomically_instead_of_appending(monkeypatch):
    from app import research_database as database

    collection = SimpleNamespace(update_one=AsyncCollectionResult(SimpleNamespace(modified_count=1)))
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))
    state = {
        "status": "running",
        "result": {"queries": [{"query": "topic"}], "sources": [], "events": []},
        "lease_expires_at": datetime.now(timezone.utc),
    }

    saved = await database.checkpoint_free_research_run(
        "workspace-1", "run-1", state, "owner-1", user_id=None
    )

    assert saved is True
    query, pipeline = collection.update_one.await_args.args
    assert query["client_id"] == "owner-1"
    assert query["user_id"] is None
    assert query["analyses"]["$elemMatch"]["analysis_id"] == "run-1"
    assert "analyses" not in pipeline[0].get("$push", {})
    assert "$map" in pipeline[0]["$set"]["analyses"]
    assert "analyses" not in pipeline[-1].get("$push", {})


@pytest.mark.asyncio
async def test_cancel_updates_current_embedded_state_atomically_and_preserves_size_bound(monkeypatch):
    from app import research_database as database

    saved_workspace = {
        "_id": "workspace-1",
        "analyses": [{
            "analysis_id": "run-1",
            "research_mode": "free_web_research",
            "status": "partial",
            "result": {"terminal": {"source_count": 1}},
        }],
    }
    collection = SimpleNamespace(
        find_one_and_update=AsyncCollectionResult(saved_workspace),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.cancel_free_research_run(
        "workspace-1", "run-1", "owner-1", user_id="user-1"
    )

    assert result == {"outcome": "cancelled", "status": "partial", "source_count": 1}
    query, pipeline = collection.find_one_and_update.await_args.args
    assert query["_id"] == "workspace-1"
    assert query["user_id"] == "user-1"
    assert query["analyses"]["$elemMatch"] == {
        "analysis_id": "run-1",
        "research_mode": "free_web_research",
        "status": "running",
    }
    assert "$bsonSize" in str(query["$expr"])
    assert pipeline[0]["$set"]["analyses"] == query["$expr"]["$lte"][0]["$bsonSize"]["$mergeObjects"][1]["analyses"]
    assert collection.find_one_and_update.await_args.kwargs["projection"] == {
        "analyses.analysis_id": 1,
        "analyses.research_mode": 1,
        "analyses.status": 1,
        "analyses.result.terminal.source_count": 1,
        "analyses.result.terminal.error_kind": 1,
    }
    assert collection.find_one_and_update.await_args.kwargs["return_document"]
    assert "$$analysis.result.sources" in str(pipeline)
    assert "$$analysis.result.events" in str(pipeline)
    assert "user_cancelled" in str(pipeline)
    assert "sources" not in pipeline[0]["$set"]


@pytest.mark.asyncio
async def test_cancel_does_not_mutate_when_workspace_size_guard_blocks(monkeypatch):
    from app import research_database as database

    collection = SimpleNamespace(
        find_one_and_update=AsyncCollectionResult(None),
        find_one=AsyncCollectionResult({
            "analyses": [{
                "analysis_id": "run-1",
                "research_mode": "free_web_research",
                "status": "running",
                "result": {"sources": []},
            }]
        }),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.cancel_free_research_run(
        "workspace-1", "run-1", "owner-1", user_id=None
    )

    assert result == {"outcome": "size_limit", "status": "running", "source_count": 0}


@pytest.mark.asyncio
async def test_cancel_retry_returns_saved_user_cancel_terminal_idempotently(monkeypatch):
    from app import research_database as database

    collection = SimpleNamespace(
        find_one_and_update=AsyncCollectionResult(None),
        find_one=AsyncCollectionResult({
            "analyses": [{
                "analysis_id": "run-1",
                "research_mode": "free_web_research",
                "status": "partial",
                "result": {
                    "terminal": {
                        "status": "partial",
                        "source_count": 2,
                        "error_kind": "user_cancelled",
                    }
                },
            }]
        }),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.cancel_free_research_run(
        "workspace-1", "run-1", "owner-1", user_id="user-1"
    )

    assert result == {"outcome": "cancelled", "status": "partial", "source_count": 2}
    assert collection.find_one.await_args.args[1]["analyses.result.terminal.error_kind"] == 1


@pytest.mark.parametrize(
    ("status", "error_kind"),
    [("complete", "complete"), ("partial", "run_deadline"), ("cancelled", "client_disconnected")],
)
@pytest.mark.asyncio
async def test_cancel_retry_keeps_conflict_for_non_user_cancel_terminal(monkeypatch, status, error_kind):
    from app import research_database as database

    collection = SimpleNamespace(
        find_one_and_update=AsyncCollectionResult(None),
        find_one=AsyncCollectionResult({
            "analyses": [{
                "analysis_id": "run-1",
                "research_mode": "free_web_research",
                "status": status,
                "result": {"terminal": {"source_count": 1, "error_kind": error_kind}},
            }]
        }),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.cancel_free_research_run(
        "workspace-1", "run-1", "owner-1", user_id=None
    )

    assert result == {"outcome": "not_running", "status": status, "source_count": 1}


@pytest.mark.asyncio
async def test_replay_marks_expired_running_lease_interrupted(monkeypatch):
    from app import research_database as database

    collection = SimpleNamespace(
        find_one=AsyncCollectionResult({
            "analyses": [{
                "analysis_id": "run-1",
                "kind": "trusted_sources",
                "research_mode": "free_web_research",
                "request_sha256": "a" * 64,
                "status": "running",
                "lease_expires_at": datetime(2026, 10, 16, tzinfo=timezone.utc),
                "result": {"sources": []},
            }]
        }),
        update_one=AsyncCollectionResult(SimpleNamespace(modified_count=1)),
    )
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(research_workspaces=collection))

    result = await database.replay_free_research_run(
        "workspace-1", "run-1", "a" * 64, "owner-1", user_id=None
    )

    assert result["outcome"] == "replay"
    assert result["analysis"]["status"] == "interrupted"
    assert "$map" in collection.update_one.await_args.args[1][0]["$set"]["analyses"]


class AsyncCollectionResult:
    def __init__(self, value):
        self.value = value
        self.await_args = None
        self.await_count = 0

    async def __call__(self, *args, **kwargs):
        self.await_args = SimpleNamespace(args=args, kwargs=kwargs)
        self.await_count += 1
        if callable(self.value):
            return self.value(*args, **kwargs)
        return self.value

