from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import re
from bson import BSON
from pymongo import ReturnDocument

from app.config import get_settings
from app.database import get_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _size_guard(record: dict) -> dict:
    # Atomic byte budget; reserve array-key/update overhead and BSON headroom.
    return {'$expr': {'$lte': [
        {'$add': [{'$bsonSize': '$$ROOT'}, len(BSON.encode(record)) + 4096]},
        12_000_000,
    ]}}


def _owner(client_id: str, user_id: str | None) -> dict[str, Any]:
    return (
        {"user_id": user_id} if user_id else {"client_id": client_id, "user_id": None}
    )


async def init_research_db() -> None:
    collection = get_db().research_workspaces
    await collection.create_index([("user_id", 1), ("updated_at", -1)])
    await collection.create_index([("client_id", 1), ("updated_at", -1)])
    await collection.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="research_workspaces_retention_ttl",
    )


async def create_workspace(
    workspace_id: str,
    title: str,
    description: str,
    client_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    now = _now()
    document = {
        "_id": workspace_id,
        "workspace_id": workspace_id,
        "title": title.strip()[:120],
        "description": description.strip()[:2_000],
        "client_id": client_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(days=get_settings().DATA_RETENTION_DAYS),
        "evidence": [],
        "analyses": [],
        "documents": [],
    }
    await get_db().research_workspaces.replace_one(
        {"_id": workspace_id}, document, upsert=True
    )
    return document


async def list_workspaces(
    client_id: str, *, user_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    bounded = min(max(1, limit), 100)
    cursor = (
        get_db()
        .research_workspaces.find(
            {**_owner(client_id, user_id), "expires_at": {"$gt": _now()}},
            {"documents.original_bytes": 0},
        )
        .sort("updated_at", -1)
        .limit(bounded)
    )
    return await cursor.to_list(length=bounded)


async def get_workspace(
    workspace_id: str, client_id: str, *, user_id: str | None = None
) -> dict[str, Any] | None:
    return await get_db().research_workspaces.find_one(
        {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": _now()}},
        {"documents.original_bytes": 0},
    )


async def get_workspace_original(
    workspace_id: str, document_id: str, client_id: str, *, user_id: str | None = None
) -> dict[str, Any] | None:
    record = await get_db().research_workspaces.find_one(
        {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": _now()}},
        {"documents": {"$elemMatch": {"document_id": document_id}}, "_id": 0},
    )
    documents = (record or {}).get("documents") or []
    if not documents or not isinstance(documents[0].get("original_bytes"), bytes):
        return None
    return documents[0]


async def update_workspace(
    workspace_id: str,
    client_id: str,
    *,
    user_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
) -> bool:
    values: dict[str, Any] = {"updated_at": _now()}
    if title is not None:
        values["title"] = title.strip()[:120]
    if description is not None:
        values["description"] = description.strip()[:2_000]
    result = await get_db().research_workspaces.update_one(
        {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": _now()}}, {"$set": values}
    )
    return result.modified_count > 0


async def delete_workspace(
    workspace_id: str, client_id: str, *, user_id: str | None = None
) -> bool:
    result = await get_db().research_workspaces.delete_one(
        {"_id": workspace_id, **_owner(client_id, user_id)}
    )
    return result.deleted_count > 0


async def pin_workspace_evidence(
    workspace_id: str,
    evidence: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    now = _now()
    result = await get_db().research_workspaces.update_one(
        {
            "_id": workspace_id,
            **_owner(client_id, user_id),
            "expires_at": {"$gt": now},
            "evidence.evidence_id": {"$ne": evidence["evidence_id"]},
            "evidence.99": {"$exists": False},
            **_size_guard(evidence),
        },
        {
            "$push": {"evidence": {**evidence, "created_at": now}},
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count > 0


async def update_evidence_review(
    workspace_id: str, evidence_id: str, review: dict, client_id: str,
    *, user_id: str | None = None, expected_version: int = 0,
) -> bool:
    match = {'evidence_id': evidence_id}
    if expected_version == 0:
        match['$or'] = [{'review.version': {'$exists': False}}, {'review.version': 0}]
    else:
        match['review.version'] = expected_version
    result = await get_db().research_workspaces.update_one(
        {'_id': workspace_id, **_owner(client_id, user_id), 'expires_at': {'$gt': _now()},
         'evidence': {'$elemMatch': match}, **_size_guard(review)},
        {'$set': {'evidence.$.review': review, 'updated_at': _now()}},
    )
    return result.modified_count > 0


async def unpin_workspace_evidence(
    workspace_id: str,
    evidence_id: str,
    client_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    result = await get_db().research_workspaces.update_one(
        {
            "_id": workspace_id,
            **_owner(client_id, user_id),
            "expires_at": {"$gt": _now()},
            "evidence.evidence_id": evidence_id,
        },
        {
            "$pull": {"evidence": {"evidence_id": evidence_id}},
            "$set": {"updated_at": _now()},
        },
    )
    return result.modified_count > 0


async def save_workspace_analysis(
    workspace_id: str,
    analysis: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
    required_document_id: str | None = None,
    required_document_ids: list[str] | None = None,
) -> bool:
    if required_document_id is not None and required_document_ids is not None:
        raise ValueError("provide required_document_id or required_document_ids, not both")
    if required_document_ids is not None and any(
        not isinstance(document_id, str) or not document_id
        for document_id in required_document_ids
    ):
        raise ValueError("required_document_ids must contain non-empty strings")
    if required_document_ids is not None and len(set(required_document_ids)) != len(
        required_document_ids
    ):
        raise ValueError("required_document_ids must be unique")
    required_ids = (
        [required_document_id]
        if required_document_id is not None
        else list(required_document_ids or [])
    )
    now = _now()
    stored_analysis = {**analysis, "created_at": now}
    if required_document_ids:
        stored_analysis["required_document_ids"] = required_ids
    query = {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": now}}
    query.update(_size_guard(stored_analysis))
    if len(required_ids) == 1:
        query["documents.document_id"] = required_ids[0]
    elif required_ids:
        query["documents.document_id"] = {"$all": required_ids}
    result = await get_db().research_workspaces.update_one(
        query,
        {
            "$push": {
                "analyses": {
                    "$each": [stored_analysis],
                    "$slice": -50,
                }
            },
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count > 0


def _free_research_owner_query(
    workspace_id: str, client_id: str, user_id: str | None, now: datetime
) -> dict[str, Any]:
    return {
        "_id": workspace_id,
        **_owner(client_id, user_id),
        "expires_at": {"$gt": now},
    }


def _free_research_run_from(workspace: dict[str, Any] | None, run_id: str):
    return next(
        (
            item
            for item in (workspace or {}).get("analyses", [])
            if item.get("analysis_id") == run_id
            and item.get("research_mode") == "free_web_research"
        ),
        None,
    )


def _cancel_free_research_transform(run_id: str, now: datetime) -> dict[str, Any]:
    """Return a current-state pipeline and exact BSON-size expression for cancellation."""
    sources = {"$ifNull": ["$$analysis.result.sources", []]}
    events = {"$ifNull": ["$$analysis.result.events", []]}
    terminal_status = {
        "$cond": [{"$gt": [{"$size": "$$sources"}, 0]}, "partial", "cancelled"]
    }
    terminal_event = {
        "type": "terminal",
        "status": "$$status",
        "analysis_id": "$$analysis.analysis_id",
        "source_count": {"$size": "$$sources"},
        "error_kind": "user_cancelled",
    }
    replacement = {
        "$let": {
            "vars": {"sources": sources, "events": events},
            "in": {
                "$let": {
                    "vars": {"status": terminal_status},
                    "in": {
                        "$mergeObjects": [
                            "$$analysis",
                            {
                                "status": "$$status",
                                "lease_expires_at": None,
                                "completed_at": {"$literal": now},
                                "updated_at": {"$literal": now},
                                "result": {
                                    "$mergeObjects": [
                                        {"$ifNull": ["$$analysis.result", {}]},
                                        {
                                            "status": "$$status",
                                            "terminal": {
                                                "status": "$$status",
                                                "analysis_id": "$$analysis.analysis_id",
                                                "source_count": {"$size": "$$sources"},
                                                "error_kind": "user_cancelled",
                                            },
                                            "events": {
                                                "$concatArrays": ["$$events", [terminal_event]]
                                            },
                                        },
                                    ]
                                },
                            },
                        ]
                    },
                }
            },
        }
    }
    is_target = {
        "$and": [
            {"$eq": ["$$analysis.analysis_id", run_id]},
            {"$eq": ["$$analysis.research_mode", "free_web_research"]},
            {"$eq": ["$$analysis.status", "running"]},
        ]
    }
    analyses = {
        "$map": {
            "input": {"$ifNull": ["$analyses", []]},
            "as": "analysis",
            "in": {"$cond": [is_target, replacement, "$$analysis"]},
        }
    }
    fields = {"analyses": analyses, "updated_at": {"$literal": now}}
    updated_root = {"$mergeObjects": ["$$ROOT", fields]}
    return {
        "fields": fields,
        "updated_root": updated_root,
    }


async def cancel_free_research_run(
    workspace_id: str,
    run_id: str,
    client_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Atomically terminalize a running owner-scoped run without losing checkpoints."""
    now = _now()
    transform = _cancel_free_research_transform(run_id, now)
    owner_query = _free_research_owner_query(workspace_id, client_id, user_id, now)
    run_match = {
        "analysis_id": run_id,
        "research_mode": "free_web_research",
        "status": "running",
    }
    query = {
        **owner_query,
        "analyses": {"$elemMatch": run_match},
        "$expr": {
            "$lte": [
                {"$bsonSize": transform["updated_root"]},
                12_000_000,
            ]
        },
    }
    projection = {
        "analyses.analysis_id": 1,
        "analyses.research_mode": 1,
        "analyses.status": 1,
        "analyses.result.terminal.source_count": 1,
        "analyses.result.terminal.error_kind": 1,
    }
    collection = get_db().research_workspaces
    updated = await collection.find_one_and_update(
        query,
        [{"$set": transform["fields"]}],
        projection=projection,
        return_document=ReturnDocument.AFTER,
    )
    if updated is not None:
        analysis = _free_research_run_from(updated, run_id)
        terminal = ((analysis or {}).get("result") or {}).get("terminal") or {}
        return {
            "outcome": "cancelled",
            "status": (analysis or {}).get("status"),
            "source_count": terminal.get("source_count", 0),
        }

    current = await collection.find_one(owner_query, projection)
    analysis = _free_research_run_from(current, run_id)
    if analysis is None:
        return {"outcome": "not_found", "status": None, "source_count": 0}
    if analysis.get("status") == "running":
        return {"outcome": "size_limit", "status": "running", "source_count": 0}
    terminal = (analysis.get("result") or {}).get("terminal") or {}
    if (
        analysis.get("status") in {"partial", "cancelled"}
        and terminal.get("error_kind") == "user_cancelled"
    ):
        return {
            "outcome": "cancelled",
            "status": analysis.get("status"),
            "source_count": terminal.get("source_count", 0),
        }
    return {
        "outcome": "not_running",
        "status": analysis.get("status"),
        "source_count": terminal.get("source_count", 0),
    }


def _replace_analysis_size_guard(run_id: str, replacement: dict[str, Any]) -> dict[str, Any]:
    new_size = len(BSON.encode(replacement))
    old_analysis = {
        "$arrayElemAt": [
            {
                "$filter": {
                    "input": {"$ifNull": ["$analyses", []]},
                    "as": "analysis",
                    "cond": {"$eq": ["$$analysis.analysis_id", run_id]},
                }
            },
            0,
        ]
    }
    return {
        "$expr": {
            "$lte": [
                {
                    "$add": [
                        {"$bsonSize": "$$ROOT"},
                        {"$max": [0, {"$subtract": [new_size, {"$bsonSize": old_analysis}]}]},
                    ]
                },
                12_000_000,
            ]
        }
    }


async def checkpoint_free_research_run(
    workspace_id: str,
    run_id: str,
    state: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    """Atomically replace a bounded embedded run checkpoint under its owner."""
    now = _now()
    replacement = {"analysis_id": run_id, "research_mode": "free_web_research", **state}
    match = {
        **_free_research_owner_query(workspace_id, client_id, user_id, now),
        "analyses": {
            "$elemMatch": {
                "analysis_id": run_id,
                "research_mode": "free_web_research",
                "status": "running",
            }
        },
        **_replace_analysis_size_guard(run_id, replacement),
    }
    result = await get_db().research_workspaces.update_one(
        match,
        [
            {
                "$set": {
                    "analyses": {
                        "$map": {
                            "input": {"$ifNull": ["$analyses", []]},
                            "as": "analysis",
                            "in": {
                                "$cond": [
                                    {"$eq": ["$$analysis.analysis_id", run_id]},
                                    {"$mergeObjects": ["$$analysis", {"$literal": replacement}]},
                                    "$$analysis",
                                ]
                            },
                        }
                    }
                }
            },
            {"$set": {"updated_at": now}},
        ],
    )
    return result.modified_count > 0


async def replay_free_research_run(
    workspace_id: str,
    run_id: str,
    request_sha256: str | None,
    client_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Read an owner-scoped run and classify stale leases as interrupted."""
    now = _now()
    workspace = await get_db().research_workspaces.find_one(
        _free_research_owner_query(workspace_id, client_id, user_id, now),
        {"analyses": {"$elemMatch": {"analysis_id": run_id}}},
    )
    analysis = _free_research_run_from(workspace, run_id)
    if analysis is None:
        return {"outcome": "not_found", "analysis": None}
    if request_sha256 is not None and analysis.get("request_sha256") != request_sha256:
        return {"outcome": "mismatch", "analysis": analysis}
    if analysis.get("status") == "running":
        lease = analysis.get("lease_expires_at")
        if isinstance(lease, datetime):
            if lease.tzinfo is None:
                lease = lease.replace(tzinfo=timezone.utc)
            stale = lease <= now
        else:
            stale = True
        if stale:
            result_state = {
                **(analysis.get("result") or {}),
                "status": "interrupted",
            }
            if not any(
                item.get("type") == "terminal"
                for item in result_state.get("events", [])
                if isinstance(item, dict)
            ):
                result_state["events"] = [
                    *(result_state.get("events") or []),
                    {
                        "type": "terminal",
                        "status": "interrupted",
                        "analysis_id": run_id,
                        "source_count": len(result_state.get("sources") or []),
                        "error_kind": "stale_lease",
                    },
                ]
            interrupted = {
                **analysis,
                "status": "interrupted",
                "lease_expires_at": None,
                "completed_at": now,
                "result": result_state,
            }
            interrupted.pop("created_at", None)
            interrupted.pop("analysis_id", None)
            interrupted.pop("research_mode", None)
            if await checkpoint_free_research_run(
                workspace_id,
                run_id,
                interrupted,
                client_id,
                user_id=user_id,
            ):
                analysis = {**analysis, **interrupted}
                return {"outcome": "replay", "analysis": analysis}
            return {"outcome": "changed", "analysis": None}
        return {"outcome": "active", "analysis": analysis}
    return {"outcome": "replay", "analysis": analysis}


async def begin_free_research_run(
    workspace_id: str,
    analysis: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Claim one workspace run with idempotency and an atomic active-run guard."""
    now = _now()
    run_id = str(analysis["analysis_id"])
    request_sha256 = str(analysis["request_sha256"])
    existing_result = await replay_free_research_run(
        workspace_id, run_id, request_sha256, client_id, user_id=user_id
    )
    if existing_result["outcome"] != "not_found":
        return existing_result

    stored = {
        **analysis,
        "analysis_id": run_id,
        "kind": "trusted_sources",
        "research_mode": "free_web_research",
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }
    match = {
        **_free_research_owner_query(workspace_id, client_id, user_id, now),
        "analyses": {
            "$not": {
                "$elemMatch": {
                    "research_mode": "free_web_research",
                    "status": "running",
                    "lease_expires_at": {"$gt": now},
                }
            }
        },
        **_size_guard(stored),
    }
    collection = get_db().research_workspaces
    result = await collection.update_one(
        match,
        [
            {
                "$set": {
                    "analyses": {
                        "$map": {
                            "input": {"$ifNull": ["$analyses", []]},
                            "as": "analysis",
                            "in": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {"$eq": ["$$analysis.research_mode", "free_web_research"]},
                                            {"$eq": ["$$analysis.status", "running"]},
                                            {"$lte": [
                                                {"$ifNull": ["$$analysis.lease_expires_at", datetime.min.replace(tzinfo=timezone.utc)]},
                                                now,
                                            ]},
                                        ]
                                    },
                                    {
                                        "$mergeObjects": [
                                            "$$analysis",
                                            {
                                                "status": "interrupted",
                                                "lease_expires_at": None,
                                                "completed_at": now,
                                                "result": {
                                                    "$mergeObjects": [
                                                        {"$ifNull": ["$$analysis.result", {}]},
                                                        {
                                                            "status": "interrupted",
                                                            "events": {
                                                                "$concatArrays": [
                                                                    {"$ifNull": ["$$analysis.result.events", []]},
                                                                    [
                                                                        {
                                                                            "$mergeObjects": [
                                                                                {
                                                                                    "$literal": {
                                                                                        "type": "terminal",
                                                                                        "status": "interrupted",
                                                                                        "error_kind": "stale_lease",
                                                                                    }
                                                                                },
                                                                                {
                                                                                    "analysis_id": "$$analysis.analysis_id",
                                                                                    "source_count": {
                                                                                        "$size": {
                                                                                            "$ifNull": ["$$analysis.result.sources", []]
                                                                                        }
                                                                                    },
                                                                                },
                                                                            ]
                                                                        }
                                                                    ],
                                                                ]
                                                            },
                                                        },
                                                    ]
                                                },
                                            },
                                        ]
                                    },
                                    "$$analysis",
                                ]
                            },
                        }
                    }
                }
            },
            {
                "$set": {
                    "analyses": {
                        "$slice": [
                            {"$concatArrays": ["$analyses", {"$literal": [stored]}]},
                            -50,
                        ]
                    },
                    "updated_at": now,
                }
            },
        ],
    )
    if result.modified_count:
        return {"outcome": "started", "analysis": stored}

    # Distinguish idempotent races and active work from an absent/expired or
    # BSON-full workspace without performing a non-atomic second mutation.
    workspace = await collection.find_one(
        _free_research_owner_query(workspace_id, client_id, user_id, now),
        {"analyses": 1},
    )
    same = _free_research_run_from(workspace, run_id)
    if same is not None:
        if same.get("request_sha256") != request_sha256:
            return {"outcome": "mismatch", "analysis": same}
        if same.get("status") == "running":
            return {"outcome": "active", "analysis": same}
        return {"outcome": "replay", "analysis": same}
    if workspace is None:
        return {"outcome": "not_found", "analysis": None}
    active = next(
        (
            item
            for item in workspace.get("analyses", [])
            if item.get("research_mode") == "free_web_research"
            and item.get("status") == "running"
            and item.get("lease_expires_at")
            and item["lease_expires_at"] > now
        ),
        None,
    )
    if active:
        return {"outcome": "active", "analysis": active}
    return {"outcome": "size_limit", "analysis": None}


async def save_full_document_review_batch(
    workspace_id: str,
    analysis: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None,
    document_id: str,
    input_sha256: str,
    completed_clause_ids: list[str],
) -> bool:
    """Atomically retain a review batch and its bounded per-document progress."""
    if len(completed_clause_ids) > 100 or len(set(completed_clause_ids)) != len(completed_clause_ids) or any(not re.fullmatch(r"[a-f0-9]{24}-\d{3}", item) for item in completed_clause_ids):
        raise ValueError("invalid_completed_clause_ids")
    now = _now()
    stored = {**analysis, "required_document_ids": [document_id], "created_at": now}
    existing = {"$ifNull": ["$$doc.full_review_progress", []]}
    same = {"$filter": {"input": existing, "as": "item", "cond": {"$eq": ["$$item.input_sha256", input_sha256]}}}
    current = {"$ifNull": [{"$arrayElemAt": [same, 0]}, {}]}
    merged = {
        "input_sha256": input_sha256,
        "completed_clause_ids": {"$setUnion": [{"$ifNull": ["$$current.completed_clause_ids", []]}, completed_clause_ids]},
        "updated_at": now,
    }
    replacement = {"$slice": [{"$concatArrays": [{"$filter": {"input": existing, "as": "item", "cond": {"$ne": ["$$item.input_sha256", input_sha256]}}}, [merged]]}, -3]}
    result = await get_db().research_workspaces.update_one(
        {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": now}, "documents.document_id": document_id, **_size_guard(stored)},
        [{"$set": {"documents": {"$map": {"input": "$documents", "as": "doc", "in": {"$cond": [{"$eq": ["$$doc.document_id", document_id]}, {"$mergeObjects": ["$$doc", {"full_review_progress": {"$let": {"vars": {"current": current}, "in": replacement}}}]}, "$$doc"]}}}, "analyses": {"$slice": [{"$concatArrays": ["$analyses", {"$literal": [stored]}]}, -50]}, "updated_at": now}}],
    )
    return result.modified_count > 0


async def save_workspace_document(
    workspace_id: str,
    document: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
    original_bytes: bytes | None = None,
) -> bool:
    now = _now()
    document_id = str(document["document_id"])
    stored = {**document, "uploaded_at": now}
    if original_bytes is not None:
        from app.services.workspace_documents import MAX_UPLOAD_BYTES

        if not isinstance(original_bytes, bytes) or not 0 < len(original_bytes) <= MAX_UPLOAD_BYTES:
            raise ValueError("invalid_original_size")
        stored.update(original_bytes=original_bytes, original_available=True)
    result = await get_db().research_workspaces.update_one(
        {
            "_id": workspace_id,
            **_owner(client_id, user_id),
            "documents.document_id": {"$ne": document_id},
            "documents.19": {"$exists": False},
            "expires_at": {"$gt": now},
            **_size_guard(stored),
        },
        {
            "$push": {"documents": stored},
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count > 0


async def remove_workspace_document(
    workspace_id: str,
    document_id: str,
    client_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    result = await get_db().research_workspaces.update_one(
        {
            "_id": workspace_id,
            **_owner(client_id, user_id),
            "documents.document_id": document_id,
            "expires_at": {"$gt": _now()},
        },
        {
            "$pull": {
                "documents": {"document_id": document_id},
                "evidence": {"workspace_document_id": document_id},
                "analyses": {
                    "$or": [
                        {"workspace_document_id": document_id},
                        {"required_document_ids": document_id},
                    ]
                },
            },
            "$set": {"updated_at": _now()},
        },
    )
    return result.modified_count > 0


async def update_finding_review(workspace_id: str, analysis_id: str, finding_index: int,
                                state: dict, client_id: str, *, user_id: str | None = None,
                                expected_version: int) -> bool:
    """Compare-and-set reviewer state without changing the generated finding."""
    if not 0 <= finding_index < 30 or expected_version < 0:
        raise ValueError("invalid_finding_revision")
    version_key = f"finding_reviews.{finding_index}.version"
    match = {"analysis_id": analysis_id, "kind": {"$in": ["contract_review", "full_document_review"]},
             f"result.findings.{finding_index}": {"$exists": True}}
    if expected_version:
        match[version_key] = expected_version
    else:
        match["$or"] = [{version_key: 0}, {version_key: {"$exists": False}}]
    now = _now()
    result = await get_db().research_workspaces.update_one(
        {"_id": workspace_id, **_owner(client_id, user_id), "expires_at": {"$gt": now},
         "analyses": {"$elemMatch": match}, **_size_guard(state)},
        {"$set": {f"analyses.$.finding_reviews.{finding_index}": state, "updated_at": now}})
    return result.modified_count > 0
