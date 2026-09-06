from types import SimpleNamespace

import pytest


class _Cursor:
    def sort(self, *_args):
        return self

    def limit(self, *_args):
        return self

    async def to_list(self, *, length):
        return []


class _Collection:
    def __init__(self):
        self.find_queries = []
        self.find_one_queries = []
        self.replace_documents = []
        self.update_calls = []
        self.delete_queries = []

    def find(self, query):
        self.find_queries.append(query)
        return _Cursor()

    async def find_one(self, query):
        self.find_one_queries.append(query)
        return None

    async def replace_one(self, query, document, *, upsert):
        self.replace_documents.append((query, document, upsert))

    async def update_one(self, query, update):
        self.update_calls.append((query, update))
        return SimpleNamespace(modified_count=1)

    async def delete_one(self, query):
        self.delete_queries.append(query)
        return SimpleNamespace(deleted_count=1)


@pytest.mark.asyncio
async def test_workspace_queries_use_authenticated_owner(monkeypatch) -> None:
    import app.research_database as research

    collection = _Collection()
    monkeypatch.setattr(
        research,
        "get_db",
        lambda: SimpleNamespace(research_workspaces=collection),
    )

    created = await research.create_workspace(
        "w-1", "Vụ việc", "Câu hỏi", "client-a", user_id="user-1"
    )
    await research.list_workspaces("client-a", user_id="user-1")
    await research.get_workspace("w-1", "client-a", user_id="user-1")
    await research.update_workspace(
        "w-1", "client-a", user_id="user-1", title="Tên mới"
    )
    await research.delete_workspace("w-1", "client-a", user_id="user-1")

    assert created["user_id"] == "user-1"
    assert collection.find_queries == [{"user_id": "user-1"}]
    assert collection.find_one_queries == [{"_id": "w-1", "user_id": "user-1"}]
    assert collection.update_calls[0][0] == {"_id": "w-1", "user_id": "user-1"}
    assert collection.delete_queries == [{"_id": "w-1", "user_id": "user-1"}]


@pytest.mark.asyncio
async def test_pin_and_unpin_are_atomic_and_owner_scoped(monkeypatch) -> None:
    import app.research_database as research

    collection = _Collection()
    monkeypatch.setattr(
        research,
        "get_db",
        lambda: SimpleNamespace(research_workspaces=collection),
    )
    evidence = {
        "evidence_id": "ev-1",
        "trace_id": "trace-1",
        "evidence_index": 0,
        "original": "Điều 1",
    }

    await research.pin_workspace_evidence("w-1", evidence, "owner-a")
    await research.unpin_workspace_evidence("w-1", "ev-1", "owner-a")

    pin_query, pin_update = collection.update_calls[0]
    assert pin_query.pop('$expr')['$lte'][1] == 12_000_000
    assert pin_query == {
        "_id": "w-1",
        "client_id": "owner-a",
        "user_id": None,
        "evidence.evidence_id": {"$ne": "ev-1"},
        "evidence.99": {"$exists": False},
    }
    assert pin_update["$push"]["evidence"]["evidence_id"] == "ev-1"
    assert collection.update_calls[1][0] == {
        "_id": "w-1",
        "client_id": "owner-a",
        "user_id": None,
        "evidence.evidence_id": "ev-1",
    }


@pytest.mark.asyncio
async def test_workspace_documents_are_bounded_duplicate_safe_and_owner_scoped(
    monkeypatch,
) -> None:
    import app.research_database as research

    collection = _Collection()
    monkeypatch.setattr(
        research,
        "get_db",
        lambda: SimpleNamespace(research_workspaces=collection),
    )
    document = {
        "document_id": "a" * 24,
        "filename": "contract.txt",
        "clauses": [],
    }

    assert await research.save_workspace_document(
        "w-1", document, "owner-a", user_id="user-1"
    )
    assert await research.remove_workspace_document(
        "w-1", "a" * 24, "owner-a", user_id="user-1"
    )

    save_query, save_update = collection.update_calls[0]
    size_guard = save_query.pop('$expr')
    assert size_guard['$lte'][0]['$add'][0] == {'$bsonSize': '$$ROOT'}
    assert size_guard['$lte'][1] == 12_000_000
    assert save_query == {
        "_id": "w-1",
        "user_id": "user-1",
        "documents.document_id": {"$ne": "a" * 24},
        "documents.19": {"$exists": False},
    }
    assert save_update["$push"]["documents"]["document_id"] == "a" * 24
    remove_query, remove_update = collection.update_calls[1]
    assert remove_query["documents.document_id"] == "a" * 24
    assert remove_update["$pull"]["evidence"]["workspace_document_id"] == "a" * 24
    assert remove_update['$pull']['analyses']['workspace_document_id'] == 'a' * 24
