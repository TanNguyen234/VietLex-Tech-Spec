from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any

from app.config import get_settings
from app.database import get_db
from app.services.accounts import token_sha256


SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def init_account_db() -> None:
    database = get_db()
    await database.users.create_index(
        [("email", 1)], unique=True, name="users_email_unique"
    )
    await database.auth_sessions.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="auth_sessions_ttl",
    )
    await database.auth_sessions.create_index([("token_hash", 1)], unique=True)
    await database.account_tokens.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="account_tokens_ttl",
    )
    await database.account_tokens.create_index([("token_hash", 1)], unique=True)


async def create_user(email: str, password_hash: str) -> dict[str, Any]:
    now = _now()
    document = {
        "_id": str(uuid.uuid4()),
        "email": email,
        "password_hash": password_hash,
        "email_verified": False,
        "created_at": now,
        "updated_at": now,
        "last_login": None,
        "schema_version": SCHEMA_VERSION,
    }
    await get_db().users.insert_one(document)
    return document


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"email": email})


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"_id": user_id})


async def mark_user_verified(user_id: str) -> bool:
    result = await get_db().users.update_one(
        {"_id": user_id},
        {"$set": {"email_verified": True, "updated_at": _now()}},
    )
    return result.modified_count > 0


async def update_password(user_id: str, password_hash: str) -> bool:
    result = await get_db().users.update_one(
        {"_id": user_id},
        {"$set": {"password_hash": password_hash, "updated_at": _now()}},
    )
    return result.modified_count > 0


async def create_auth_session(user_id: str, token: str) -> None:
    settings = get_settings()
    await get_db().auth_sessions.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "token_hash": token_sha256(token),
            "created_at": _now(),
            "expires_at": _now() + timedelta(days=settings.AUTH_SESSION_DAYS),
            "schema_version": SCHEMA_VERSION,
        }
    )


async def resolve_auth_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    database = get_db()
    session = await database.auth_sessions.find_one(
        {"token_hash": token_sha256(token)}
    )
    if not session or _as_utc(session.get("expires_at", _now())) <= _now():
        return None
    return await database.users.find_one({"_id": session["user_id"]})


async def revoke_auth_session(token: str | None) -> None:
    if token:
        await get_db().auth_sessions.delete_one(
            {"token_hash": token_sha256(token)}
        )


async def create_account_token(
    user_id: str, purpose: str, token: str
) -> None:
    lifetime = timedelta(hours=24 if purpose == "verify_email" else 1)
    collection = get_db().account_tokens
    await collection.delete_many({"user_id": user_id, "purpose": purpose})
    await collection.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "purpose": purpose,
            "token_hash": token_sha256(token),
            "created_at": _now(),
            "expires_at": _now() + lifetime,
            "schema_version": SCHEMA_VERSION,
        }
    )


async def consume_account_token(token: str, purpose: str) -> str | None:
    document = await get_db().account_tokens.find_one_and_delete(
        {"token_hash": token_sha256(token), "purpose": purpose}
    )
    if not document or _as_utc(document.get("expires_at", _now())) <= _now():
        return None
    return str(document["user_id"])


async def claim_anonymous_history(user_id: str, client_id: str) -> None:
    database = get_db()
    update = {"$set": {"user_id": user_id}}
    anonymous_owner = {"client_id": client_id, "user_id": None}
    await database.chat_sessions.update_many(anonymous_owner, update)
    await database.evaluation_logs.update_many(anonymous_owner, update)


async def export_account(user_id: str) -> dict[str, Any] | None:
    database = get_db()
    user = await database.users.find_one({"_id": user_id})
    if not user:
        return None
    public_user = {
        key: value
        for key, value in user.items()
        if key not in {"password_hash"}
    }
    sessions = await database.chat_sessions.find(
        {"user_id": user_id}
    ).sort("timestamp", 1).to_list(length=10_000)
    interactions = await database.evaluation_logs.find(
        {"user_id": user_id}
    ).sort("timestamp", 1).to_list(length=100_000)
    return {
        "schema_version": SCHEMA_VERSION,
        "user": public_user,
        "sessions": sessions,
        "interactions": interactions,
    }


async def delete_account_history(user_id: str) -> None:
    database = get_db()
    await database.chat_sessions.delete_many({"user_id": user_id})
    await database.evaluation_logs.delete_many({"user_id": user_id})


async def delete_account(user_id: str) -> None:
    database = get_db()
    await database.auth_sessions.delete_many({"user_id": user_id})
    await database.account_tokens.delete_many({"user_id": user_id})
    await database.chat_sessions.delete_many({"user_id": user_id})
    await database.evaluation_logs.delete_many({"user_id": user_id})
    await database.users.delete_one({"_id": user_id})
