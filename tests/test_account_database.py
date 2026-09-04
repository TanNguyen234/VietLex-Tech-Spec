from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import re

import pytest


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, *, length):
        return self.rows[:length]


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.indexes = []
        self.queries = []
        self.updates = []
        self.deletes = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    async def insert_one(self, document):
        self.rows.append(dict(document))
        return SimpleNamespace(inserted_id=document["_id"])

    async def find_one(self, query, projection=None):
        self.queries.append(query)
        return next((row for row in self.rows if _matches(row, query)), None)

    async def find_one_and_delete(self, query):
        self.queries.append(query)
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                return self.rows.pop(index)
        return None

    def find(self, query, projection=None):
        self.queries.append(query)
        return _Cursor([row for row in self.rows if _matches(row, query)])

    async def update_one(self, query, update):
        self.updates.append((query, update))
        for row in self.rows:
            if _matches(row, query):
                row.update(update.get("$set", {}))
                return SimpleNamespace(modified_count=1, matched_count=1)
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def update_many(self, query, update):
        self.updates.append((query, update))
        changed = 0
        for row in self.rows:
            if _matches(row, query):
                row.update(update.get("$set", {}))
                changed += 1
        return SimpleNamespace(modified_count=changed)

    async def delete_one(self, query):
        self.deletes.append(query)
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return SimpleNamespace(deleted_count=before - len(self.rows))

    async def delete_many(self, query):
        self.deletes.append(query)
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return SimpleNamespace(deleted_count=before - len(self.rows))

    async def count_documents(self, query):
        return sum(1 for row in self.rows if _matches(row, query))


def _matches(row, query):
    for key, value in query.items():
        if key == "$and":
            if not all(_matches(row, item) for item in value):
                return False
            continue
        if key == "$or":
            if not any(_matches(row, item) for item in value):
                return False
            continue
        actual = row.get(key)
        if isinstance(value, dict) and "$ne" in value:
            if actual == value["$ne"]:
                return False
        elif isinstance(value, dict) and "$exists" in value:
            if (key in row) is not bool(value["$exists"]):
                return False
        elif isinstance(value, dict) and "$gt" in value:
            if actual is None or actual <= value["$gt"]:
                return False
        elif isinstance(value, dict) and "$regex" in value:
            if not re.search(value["$regex"], str(actual or ""), re.IGNORECASE):
                return False
        elif actual != value:
            return False
    return True


def _database():
    return SimpleNamespace(
        users=_Collection(),
        auth_sessions=_Collection(),
        account_tokens=_Collection(),
        admin_audit_logs=_Collection(),
        chat_sessions=_Collection(),
        evaluation_logs=_Collection(),
    )


@pytest.mark.asyncio
async def test_account_indexes_enforce_identity_and_expiry(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.init_account_db()

    assert database.users.indexes[0][1]["unique"] is True
    assert database.auth_sessions.indexes[0][1]["expireAfterSeconds"] == 0
    assert database.account_tokens.indexes[0][1]["expireAfterSeconds"] == 0


@pytest.mark.asyncio
async def test_tokens_are_stored_as_hashes_and_consumed_once(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.create_account_token("user-1", "verify_email", "raw-token")

    stored = database.account_tokens.rows[0]
    assert stored["token_hash"] != "raw-token"
    assert "raw-token" not in repr(stored)
    assert await accounts.consume_account_token("raw-token", "verify_email") == "user-1"
    assert await accounts.consume_account_token("raw-token", "verify_email") is None


@pytest.mark.asyncio
async def test_auth_session_resolves_user_without_storing_raw_token(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.append({"_id": "user-1", "email": "u@example.com"})
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.create_auth_session("user-1", "session-token")
    user = await accounts.resolve_auth_session("session-token")

    assert database.auth_sessions.rows[0]["token_hash"] != "session-token"
    assert user["_id"] == "user-1"


@pytest.mark.asyncio
async def test_auth_session_accepts_naive_utc_datetime_from_mongodb(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.append({"_id": "user-1", "email": "u@example.com"})
    database.auth_sessions.rows.append(
        {
            "user_id": "user-1",
            "token_hash": accounts.token_sha256("session-token"),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).replace(tzinfo=None),
        }
    )
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    user = await accounts.resolve_auth_session("session-token")

    assert user and user["_id"] == "user-1"


@pytest.mark.asyncio
async def test_claim_history_sets_user_id_only_for_matching_anonymous_owner(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.chat_sessions.rows.extend(
        [
            {"_id": "mine", "client_id": "client-a"},
            {
                "_id": "already-owned",
                "client_id": "client-a",
                "user_id": "user-previous",
            },
            {"_id": "other", "client_id": "client-b"},
        ]
    )
    database.evaluation_logs.rows.extend(
        [
            {"_id": "log-mine", "client_id": "client-a"},
            {
                "_id": "log-already-owned",
                "client_id": "client-a",
                "user_id": "user-previous",
            },
            {"_id": "log-other", "client_id": "client-b"},
        ]
    )
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.claim_anonymous_history("user-1", "client-a")

    assert database.chat_sessions.rows[0]["user_id"] == "user-1"
    assert database.chat_sessions.rows[1]["user_id"] == "user-previous"
    assert "user_id" not in database.chat_sessions.rows[2]
    assert database.evaluation_logs.rows[0]["user_id"] == "user-1"
    assert database.evaluation_logs.rows[1]["user_id"] == "user-previous"
    assert "user_id" not in database.evaluation_logs.rows[2]


@pytest.mark.asyncio
async def test_account_deletion_cascades_by_user_id(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.delete_account("user-1")

    assert database.users.deletes == [{"_id": "user-1"}]
    assert database.auth_sessions.deletes == [{"user_id": "user-1"}]
    assert database.account_tokens.deletes == [{"user_id": "user-1"}]
    assert database.chat_sessions.deletes == [{"user_id": "user-1"}]
    assert database.evaluation_logs.deletes == [{"user_id": "user-1"}]


@pytest.mark.asyncio
async def test_new_user_has_safe_role_and_status_defaults(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    user = await accounts.create_user("u@example.com", "hash")

    assert user["role"] == "user"
    assert user["status"] == "active"


@pytest.mark.asyncio
async def test_disabled_user_existing_session_is_rejected(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.append({
        "_id": "user-1", "email": "u@example.com", "status": "disabled"
    })
    database.auth_sessions.rows.append({
        "_id": "session-1",
        "user_id": "user-1",
        "token_hash": accounts.token_sha256("session-token"),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    assert await accounts.resolve_auth_session("session-token") is None


@pytest.mark.asyncio
async def test_password_update_revokes_existing_sessions(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.append({"_id": "user-1", "password_hash": "old"})
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    assert await accounts.update_password("user-1", "new") is True
    assert database.auth_sessions.deletes == [{"user_id": "user-1"}]


@pytest.mark.asyncio
async def test_disabling_user_revokes_sessions_and_preserves_last_admin(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.extend([
        {"_id": "admin-1", "role": "admin", "status": "active"},
        {"_id": "user-1", "role": "user", "status": "active"},
    ])
    database.auth_sessions.rows.append({"_id": "s1", "user_id": "user-1"})
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    assert await accounts.set_user_status("user-1", "disabled") is True
    assert database.auth_sessions.rows == []
    with pytest.raises(ValueError, match="management command"):
        await accounts.set_user_status("admin-1", "disabled")


@pytest.mark.asyncio
async def test_admin_audit_metadata_drops_sensitive_fields(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    await accounts.write_admin_audit(
        "admin-1", "sessions_revoked", "user", "user-1",
        metadata={"reason": "support", "token": "secret"},
    )

    record = database.admin_audit_logs.rows[0]
    assert record["metadata"] == {"reason": "support"}
    assert "secret" not in repr(record)


@pytest.mark.asyncio
async def test_session_listing_never_returns_token_hash(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.auth_sessions.rows.append({
        "_id": "session-1",
        "user_id": "user-1",
        "token_hash": accounts.token_sha256("raw-token"),
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    sessions = await accounts.list_auth_sessions(
        "user-1", current_token="raw-token"
    )

    assert sessions[0]["current"] is True
    assert "token_hash" not in sessions[0]
    assert "raw-token" not in repr(sessions)


@pytest.mark.asyncio
async def test_user_listing_searches_and_resolves_legacy_defaults(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.extend([
        {"_id": "legacy", "email": "legacy@example.com"},
        {"_id": "disabled", "email": "other@example.com", "status": "disabled"},
    ])
    database.auth_sessions.rows.append({
        "user_id": "legacy",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    users = await accounts.list_users(
        search="legacy", status="active", role="user", limit=25
    )

    assert len(users) == 1
    assert users[0]["role"] == "user"
    assert users[0]["status"] == "active"
    assert users[0]["active_session_count"] == 1


@pytest.mark.asyncio
async def test_idempotent_user_role_does_not_revoke_sessions(monkeypatch) -> None:
    import app.account_database as accounts

    database = _database()
    database.users.rows.append({"_id": "user-1", "role": "user"})
    database.auth_sessions.rows.append({"_id": "session-1", "user_id": "user-1"})
    monkeypatch.setattr(accounts, "get_db", lambda: database)

    assert await accounts.set_user_role("user-1", "user") is True
    assert database.auth_sessions.deletes == []
