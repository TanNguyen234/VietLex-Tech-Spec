from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bson import BSON


@pytest.mark.asyncio
async def test_original_and_metadata_share_atomic_size_and_retention_boundary(monkeypatch):
    import app.research_database as db
    collection = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(modified_count=1)))
    monkeypatch.setattr(db, 'get_db', lambda: SimpleNamespace(research_workspaces=collection))
    document = {'document_id': 'a' * 24, 'filename': 'test.txt'}
    payload = b'x' * 4096
    assert await db.save_workspace_document('w', document, 'client', user_id='owner', original_bytes=payload)
    query, update = collection.update_one.await_args.args
    saved = update['$push']['documents']
    assert query['user_id'] == 'owner'
    assert query['expires_at']['$gt']
    assert saved['original_bytes'] == payload
    assert saved['original_available'] is True
    assert query['$expr']['$lte'][0]['$add'][1] >= len(BSON.encode(saved))
    assert query['$expr']['$lte'][1] == 12_000_000
    assert 'original_bytes' not in document


@pytest.mark.asyncio
async def test_normal_reads_exclude_binary_and_expired_workspaces(monkeypatch):
    import app.research_database as db
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    collection = SimpleNamespace(find=Mock(return_value=cursor), find_one=AsyncMock(return_value=None))
    monkeypatch.setattr(db, 'get_db', lambda: SimpleNamespace(research_workspaces=collection))
    await db.list_workspaces('client', user_id='owner')
    await db.get_workspace('w', 'client', user_id='owner')
    for call in [collection.find.call_args, collection.find_one.await_args]:
        query, projection = call.args
        assert query['user_id'] == 'owner'
        assert query['expires_at']['$gt']
        assert projection == {'documents.original_bytes': 0}


@pytest.mark.asyncio
async def test_original_reader_confines_owner_document_and_expiry(monkeypatch):
    import app.research_database as db
    collection = SimpleNamespace(find_one=AsyncMock(return_value={'documents': [{'document_id': 'doc', 'original_bytes': b'original'}]}))
    monkeypatch.setattr(db, 'get_db', lambda: SimpleNamespace(research_workspaces=collection))
    result = await db.get_workspace_original('w', 'doc', 'client', user_id='owner')
    assert result['original_bytes'] == b'original'
    query, projection = collection.find_one.await_args.args
    assert query['_id'] == 'w' and query['user_id'] == 'owner'
    assert query['expires_at']['$gt']
    assert projection['documents']['$elemMatch']['document_id'] == 'doc'
    collection.find_one.return_value = {'documents': [{'document_id': 'doc'}]}
    assert await db.get_workspace_original('w', 'doc', 'client', user_id='owner') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [b'', b'x' * 10_000_001], ids=['empty', 'oversized'])
async def test_invalid_original_never_reaches_database(monkeypatch, payload):
    import app.research_database as db
    database = Mock(side_effect=AssertionError('must not reach database'))
    monkeypatch.setattr(db, 'get_db', database)
    with pytest.raises(ValueError, match='invalid_original_size'):
        await db.save_workspace_document('w', {'document_id': 'doc'}, 'client', original_bytes=payload)
    database.assert_not_called()
