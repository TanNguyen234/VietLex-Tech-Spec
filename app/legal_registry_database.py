"""Durable, explicitly published legal reviews, independent of workspace retention."""

from datetime import datetime, timezone
from pymongo.errors import PyMongoError
from app.database import get_db
from app.services.legal_effect import _normalize


class RegistryUnavailable(RuntimeError):
    pass


async def registry_records(document_number=None, *, skip=0):
    query = (
        {"state": "published", "document_numbers": _normalize(document_number)}
        if document_number
        else {}
    )
    limit = 201 if document_number else 26
    try:
        rows = (
            await get_db()
            .legal_effect_registry.find(query)
            .sort("published_at", -1)
            .skip(skip)
            .limit(limit)
            .to_list(length=limit)
        )
    except (PyMongoError, ValueError, RuntimeError) as error:
        raise RegistryUnavailable("legal_registry_unavailable") from error
    if document_number and len(rows) > 200:
        raise RegistryUnavailable("legal_registry_scope_too_large")
    return rows


async def publish_review(record):
    try:
        collection = get_db().legal_effect_registry
        await collection.create_index([("document_numbers", 1), ("state", 1)])
        await collection.update_one(
            {"_id": record["_id"]}, {"$setOnInsert": record}, upsert=True
        )
        existing = await collection.find_one({"_id": record["_id"]})
    except (PyMongoError, ValueError, RuntimeError) as error:
        raise RegistryUnavailable("legal_registry_write_unavailable") from error
    if not existing or existing.get("state") != "published":
        raise ValueError("review_already_withdrawn")
    return existing


async def withdraw_review(review_id, actor, reason):
    if not actor or not reason.strip():
        raise ValueError("withdrawal_reason_required")
    try:
        result = await get_db().legal_effect_registry.update_one(
            {"_id": review_id, "state": "published"},
            {
                "$set": {
                    "state": "withdrawn",
                    "withdrawal": {
                        "actor": str(actor),
                        "reason": reason.strip(),
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            },
        )
    except (PyMongoError, ValueError, RuntimeError) as error:
        raise RegistryUnavailable("legal_registry_write_unavailable") from error
    return result.modified_count == 1
