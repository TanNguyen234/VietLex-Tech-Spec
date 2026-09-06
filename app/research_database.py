from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
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
        .research_workspaces.find(_owner(client_id, user_id))
        .sort("updated_at", -1)
        .limit(bounded)
    )
    return await cursor.to_list(length=bounded)


async def get_workspace(
    workspace_id: str, client_id: str, *, user_id: str | None = None
) -> dict[str, Any] | None:
    return await get_db().research_workspaces.find_one(
        {"_id": workspace_id, **_owner(client_id, user_id)}
    )


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
) -> bool:
    now = _now()
    query = {"_id": workspace_id, **_owner(client_id, user_id)}
    query.update(_size_guard(analysis))
    if required_document_id is not None:
        query["documents.document_id"] = required_document_id
    result = await get_db().research_workspaces.update_one(
        query,
        {
            "$push": {
                "analyses": {
                    "$each": [{**analysis, "created_at": now}],
                    "$slice": -50,
                }
            },
            "$set": {"updated_at": now},
        },
    )
    return result.modified_count > 0


async def save_workspace_document(
    workspace_id: str,
    document: dict[str, Any],
    client_id: str,
    *,
    user_id: str | None = None,
) -> bool:
    now = _now()
    document_id = str(document["document_id"])
    result = await get_db().research_workspaces.update_one(
        {
            "_id": workspace_id,
            **_owner(client_id, user_id),
            "documents.document_id": {"$ne": document_id},
            "documents.19": {"$exists": False},
            **_size_guard(document),
        },
        {
            "$push": {"documents": {**document, "uploaded_at": now}},
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
                "analyses": {"workspace_document_id": document_id},
            },
            "$set": {"updated_at": _now()},
        },
    )
    return result.modified_count > 0
