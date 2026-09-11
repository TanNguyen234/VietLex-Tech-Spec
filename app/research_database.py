from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import re
from bson import BSON

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
        {"_id": workspace_id, **_owner(client_id, user_id)}, {"$set": values}
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
    query = {"_id": workspace_id, **_owner(client_id, user_id)}
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
        {"_id": workspace_id, **_owner(client_id, user_id), "documents.document_id": document_id, **_size_guard(stored)},
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
