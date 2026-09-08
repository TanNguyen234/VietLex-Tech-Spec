from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
import re
from typing import Any

from app.config import get_settings
from app.database import get_db
from app.services.accounts import token_sha256


SCHEMA_VERSION = 2
DEFAULT_ROLE = "user"
DEFAULT_STATUS = "active"


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
    await database.admin_audit_logs.create_index([("timestamp", -1)])
    await database.admin_audit_logs.create_index(
        [("administrator_user_id", 1), ("timestamp", -1)]
    )


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
        "role": DEFAULT_ROLE,
        "status": DEFAULT_STATUS,
        "schema_version": SCHEMA_VERSION,
    }
    await get_db().users.insert_one(document)
    return document


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"email": email})


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    return await get_db().users.find_one({"_id": user_id})


def effective_role(user: dict[str, Any]) -> str:
    return "admin" if user.get("role") == "admin" else DEFAULT_ROLE


def effective_status(user: dict[str, Any]) -> str:
    return "disabled" if user.get("status") == "disabled" else DEFAULT_STATUS


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
    if getattr(result, "matched_count", 0) > 0 or result.modified_count > 0:
        await get_db().auth_sessions.delete_many({"user_id": user_id})
        return True
    return False


async def mark_last_login(user_id: str) -> None:
    now = _now()
    await get_db().users.update_one(
        {"_id": user_id},
        {"$set": {"last_login": now, "updated_at": now}},
    )


async def create_auth_session(
    user_id: str, token: str, *, user_agent: str | None = None
) -> str:
    settings = get_settings()
    session_id = str(uuid.uuid4())
    now = _now()
    await get_db().auth_sessions.insert_one(
        {
            "_id": session_id,
            "user_id": user_id,
            "token_hash": token_sha256(token),
            "created_at": now,
            "last_used_at": now,
            "expires_at": now + timedelta(days=settings.AUTH_SESSION_DAYS),
            "user_agent": str(user_agent or "")[:200],
            "schema_version": SCHEMA_VERSION,
        }
    )
    return session_id


async def resolve_auth_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    database = get_db()
    session = await database.auth_sessions.find_one(
        {"token_hash": token_sha256(token)}
    )
    if not session or _as_utc(session.get("expires_at", _now())) <= _now():
        return None
    user = await database.users.find_one({"_id": session["user_id"]})
    if not user or effective_status(user) != DEFAULT_STATUS:
        return None
    await database.auth_sessions.update_one(
        {"token_hash": session["token_hash"]},
        {"$set": {"last_used_at": _now()}},
    )
    return {**user, "role": effective_role(user), "status": effective_status(user)}


async def revoke_auth_session(token: str | None) -> None:
    if token:
        await get_db().auth_sessions.delete_one(
            {"token_hash": token_sha256(token)}
        )


async def revoke_all_auth_sessions(user_id: str) -> None:
    await get_db().auth_sessions.delete_many({"user_id": user_id})


async def list_auth_sessions(
    user_id: str, *, current_token: str | None = None
) -> list[dict[str, Any]]:
    rows = await get_db().auth_sessions.find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(length=100)
    current_hash = token_sha256(current_token) if current_token else None
    return [
        {
            "id": str(row["_id"]),
            "created_at": row.get("created_at"),
            "last_used_at": row.get("last_used_at"),
            "expires_at": row.get("expires_at"),
            "user_agent": str(row.get("user_agent", ""))[:200],
            "current": bool(current_hash and row.get("token_hash") == current_hash),
        }
        for row in rows
    ]


async def revoke_auth_session_by_id(user_id: str, session_id: str) -> bool:
    result = await get_db().auth_sessions.delete_one(
        {"_id": session_id, "user_id": user_id}
    )
    return bool(getattr(result, "deleted_count", 0))


async def revoke_other_auth_sessions(user_id: str, current_token: str) -> int:
    result = await get_db().auth_sessions.delete_many(
        {"user_id": user_id, "token_hash": {"$ne": token_sha256(current_token)}}
    )
    return int(getattr(result, "deleted_count", 0))


async def list_users(
    *, search: str = "", status: str = "", role: str = "", skip: int = 0, limit: int = 50
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    if search:
        clauses.append({"$or": [
            {"email": {"$regex": re.escape(search[:100]), "$options": "i"}},
            {"_id": search[:100]},
        ]})
    if status == "active":
        clauses.append({"$or": [{"status": "active"}, {"status": {"$exists": False}}]})
    elif status == "disabled":
        clauses.append({"status": "disabled"})
    if role == "user":
        clauses.append({"$or": [{"role": "user"}, {"role": {"$exists": False}}]})
    elif role == "admin":
        clauses.append({"role": "admin"})
    query: dict[str, Any] = {"$and": clauses} if clauses else {}
    rows = await get_db().users.find(
        query,
        {"password_hash": 0},
    ).sort("created_at", -1).skip(max(0, skip)).limit(min(max(1, limit), 100)).to_list(
        length=min(max(1, limit), 100)
    )
    results = []
    database = get_db()
    for row in rows:
        results.append({
            **row,
            "role": effective_role(row),
            "status": effective_status(row),
            "active_session_count": await database.auth_sessions.count_documents(
                {"user_id": str(row["_id"]), "expires_at": {"$gt": _now()}}
            ),
        })
    return results


async def set_user_status(user_id: str, account_status: str) -> bool:
    if account_status not in {"active", "disabled"}:
        raise ValueError("invalid account status")
    database = get_db()
    user = await database.users.find_one({"_id": user_id})
    if not user:
        return False
    if account_status == "disabled" and effective_role(user) == "admin":
        raise ValueError(
            "administrator accounts must be demoted with the management command before disabling"
        )
    result = await database.users.update_one(
        {"_id": user_id},
        {"$set": {"status": account_status, "updated_at": _now()}},
    )
    if account_status == "disabled":
        await revoke_all_auth_sessions(user_id)
    return bool(getattr(result, "matched_count", 0) or result.modified_count > 0)


async def set_user_role(user_id: str, role: str) -> bool:
    """Management-command-only role mutation; never expose on public routes."""
    if role not in {"user", "admin"}:
        raise ValueError("invalid account role")
    database = get_db()
    user = await database.users.find_one({"_id": user_id})
    if not user:
        return False
    was_admin = effective_role(user) == "admin"
    if role == "user" and was_admin:
        usable_admins = await database.users.count_documents(
            {"role": "admin", "status": {"$ne": "disabled"}}
        )
        if effective_status(user) == "active" and usable_admins <= 1:
            raise ValueError("cannot revoke the last active administrator")
    result = await database.users.update_one(
        {"_id": user_id},
        {"$set": {"role": role, "updated_at": _now()}},
    )
    if role == "user" and was_admin:
        await revoke_all_auth_sessions(user_id)
    return bool(getattr(result, "matched_count", 0) or result.modified_count > 0)


async def write_admin_audit(
    administrator_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    *,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    bounded_metadata = {
        str(key)[:64]: str(value)[:200]
        for key, value in (metadata or {}).items()
        if not any(
            sensitive in str(key).casefold()
            for sensitive in ("password", "token", "cookie", "authorization", "api_key", "secret")
        )
    }
    await get_db().admin_audit_logs.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "timestamp": _now(),
            "administrator_user_id": administrator_user_id,
            "action": action[:64],
            "target_type": target_type[:64],
            "target_id": target_id[:200],
            "request_id": str(request_id or "")[:100],
            "metadata": bounded_metadata,
            "schema_version": SCHEMA_VERSION,
        }
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
    await database.research_workspaces.update_many(anonymous_owner, update)


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
    research_workspaces = await database.research_workspaces.find(
        {"user_id": user_id}, {"documents.original_bytes": 0}
    ).sort("created_at", 1).to_list(length=10_000)
    return {
        "schema_version": SCHEMA_VERSION,
        "user": public_user,
        "sessions": sessions,
        "interactions": interactions,
        "research_workspaces": [
            {key: value for key, value in workspace.items() if key in {
                "workspace_id", "title", "description", "created_at", "updated_at",
                "expires_at", "evidence", "analyses",
            }}
            for workspace in research_workspaces
        ],
    }


async def delete_account_history(user_id: str) -> None:
    database = get_db()
    await database.chat_sessions.delete_many({"user_id": user_id})
    await database.evaluation_logs.delete_many({"user_id": user_id})
    await database.research_workspaces.delete_many({"user_id": user_id})


async def delete_account(user_id: str) -> None:
    database = get_db()
    await database.auth_sessions.delete_many({"user_id": user_id})
    await database.account_tokens.delete_many({"user_id": user_id})
    await database.chat_sessions.delete_many({"user_id": user_id})
    await database.evaluation_logs.delete_many({"user_id": user_id})
    await database.research_workspaces.delete_many({"user_id": user_id})
    await database.users.delete_one({"_id": user_id})
