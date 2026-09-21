import pytest
from unittest.mock import AsyncMock, MagicMock
from pymongo.errors import ConnectionFailure


@pytest.mark.asyncio
async def test_store_failure_is_not_empty_registry(monkeypatch):
    from app import legal_registry_database as store

    db = MagicMock()
    db.legal_effect_registry.find.side_effect = ConnectionFailure("offline")
    monkeypatch.setattr(store, "get_db", lambda: db)
    with pytest.raises(store.RegistryUnavailable):
        await store.registry_records("A/2020")


@pytest.mark.asyncio
async def test_withdrawal_is_atomic_and_keeps_original_review(monkeypatch):
    from app import legal_registry_database as store

    db = MagicMock()
    db.legal_effect_registry.update_one = AsyncMock(
        return_value=MagicMock(modified_count=1)
    )
    monkeypatch.setattr(store, "get_db", lambda: db)
    assert await store.withdraw_review("review-1", "admin", "Incorrect scope")
    query, update = db.legal_effect_registry.update_one.call_args.args
    assert query == {"_id": "review-1", "state": "published"}
    assert update["$set"]["state"] == "withdrawn"
    assert update["$set"]["withdrawal"]["reason"] == "Incorrect scope"
    assert "assertions" not in update["$set"]


@pytest.mark.asyncio
async def test_publish_retry_does_not_reactivate_withdrawn_record(monkeypatch):
    from app import legal_registry_database as store

    db = MagicMock()
    col = db.legal_effect_registry
    col.create_index = AsyncMock()
    col.update_one = AsyncMock()
    col.find_one = AsyncMock(return_value={"state": "withdrawn"})
    monkeypatch.setattr(store, "get_db", lambda: db)
    with pytest.raises(ValueError, match="review_already_withdrawn"):
        await store.publish_review({"_id": "review-1", "state": "published"})
    assert "$setOnInsert" in col.update_one.call_args.args[1]


@pytest.mark.asyncio
async def test_registry_batch_is_published_bounded_and_rejects_truncation(monkeypatch):
    from app import legal_registry_database as store
    db = MagicMock()
    cursor = db.legal_effect_registry.find.return_value
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    monkeypatch.setattr(store, 'get_db', lambda: db)
    assert await store.registry_records_batch(['A/2020', 'a/2020']) == []
    assert db.legal_effect_registry.find.call_args.args[0] == {
        'state': 'published', 'document_numbers': {'$in': ['a/2020']}}
    cursor.limit.assert_called_once_with(201)
    cursor.to_list.return_value = [{}] * 201
    with pytest.raises(store.RegistryUnavailable):
        await store.registry_records_batch(['A/2020'])
    with pytest.raises(ValueError):
        await store.registry_records_batch([str(i) for i in range(21)])
