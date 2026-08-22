from types import SimpleNamespace

import pytest


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    def skip(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, *, length):
        return self.rows[:length]


class _Collection:
    def __init__(self):
        self.find_queries = []
        self.delete_queries = []
        self.update_queries = []
        self.replace_documents = []

    def find(self, query):
        self.find_queries.append(query)
        return _Cursor([])

    async def find_one(self, query):
        self.find_queries.append(query)
        return None

    async def replace_one(self, query, document, *, upsert):
        self.replace_documents.append((query, document, upsert))

    async def delete_one(self, query):
        self.delete_queries.append(query)

    async def delete_many(self, query):
        self.delete_queries.append(query)

    async def update_one(self, query, update):
        self.update_queries.append((query, update))
        return SimpleNamespace(modified_count=1)


@pytest.mark.asyncio
async def test_session_queries_are_scoped_to_owner(monkeypatch) -> None:
    import app.database as database

    sessions = _Collection()
    logs = _Collection()
    monkeypatch.setattr(
        database,
        "get_db",
        lambda: SimpleNamespace(chat_sessions=sessions, evaluation_logs=logs),
    )

    await database.create_session("s-1", "Hợp đồng", client_id="owner-a")
    await database.get_sessions("owner-a", search_query="hợp [đồng]")
    await database.get_session_messages("s-1", "owner-a")
    await database.rename_session("s-1", "Tên mới", "owner-a")
    await database.delete_session("s-1", "owner-a")

    assert sessions.replace_documents[0][1]["client_id"] == "owner-a"
    assert sessions.find_queries == [
        {
            "client_id": "owner-a",
            "title": {"$regex": "hợp\\ \\[đồng\\]", "$options": "i"},
        }
    ]
    assert logs.find_queries == [{"session_id": "s-1", "client_id": "owner-a"}]
    assert sessions.update_queries[0][0] == {
        "_id": "s-1",
        "client_id": "owner-a",
    }
    assert sessions.delete_queries == [{"_id": "s-1", "client_id": "owner-a"}]
    assert logs.delete_queries == [{"session_id": "s-1", "client_id": "owner-a"}]


@pytest.mark.asyncio
async def test_owned_interaction_requires_trace_and_owner(monkeypatch) -> None:
    import app.database as database

    logs = _Collection()
    monkeypatch.setattr(
        database,
        "get_db",
        lambda: SimpleNamespace(evaluation_logs=logs),
    )

    await database.get_owned_interaction("trace-1", "owner-a")

    assert logs.find_queries == [{"_id": "trace-1", "client_id": "owner-a"}]
