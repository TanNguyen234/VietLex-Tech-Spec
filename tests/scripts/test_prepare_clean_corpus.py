import hashlib
from pathlib import Path
import sqlite3

import pyarrow.parquet as pq
import pyarrow as pa
import pytest
import zstandard

from app.ingestion.content_store import SCHEMA, ContentStore
from scripts.prepare_clean_corpus import prepare_delta


def test_clean_delta_preserves_base_and_reads_back(tmp_path):
    base = tmp_path / 'base.sqlite3'
    text = 'Điều 1. Giữ nguyên.\n\nPlease sign up or sign in to your TVPL Pro Membership to see English documents.\n\nĐiều 2. ...'
    digest = hashlib.sha256(text.encode()).hexdigest()
    with sqlite3.connect(base) as db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)', (1,'1/2020','Luật','https://example.org','Luật','','Quốc hội','2020-01-01','','[]'))
        db.execute('INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)', (1,zstandard.ZstdCompressor().compress(text.encode()),len(text.encode()),digest,'shard',0,20,'[]'))
    before = base.read_bytes()
    output = tmp_path / 'new'
    raw = tmp_path / 'raw'
    raw.mkdir()
    pq.write_table(pa.Table.from_pylist([{'id':1, 'content':text}]), raw / 'shard')
    inventory = [{'document_id':1,'raw_sha256':digest,'shard':'shard','row_zero_based':0}]
    with pytest.raises(ValueError, match='raw_parquet_hash_mismatch'):
        prepare_delta(base, [dict(inventory[0], raw_sha256='0'*64)], tmp_path / 'bad', source_dir=raw)
    report = prepare_delta(base, inventory, output, source_dir=raw)
    assert base.read_bytes() == before
    assert report['changed_documents'] == 1
    assert ContentStore(output / 'original-delta.sqlite3').get_many([1])[1].content == text
    clean = ContentStore(output / 'clean-delta.sqlite3').get_many([1])[1]
    assert 'TVPL' not in clean.content
    assert 'Điều 2. ...' in clean.content
    rows = pq.read_table(output / 'clean-delta.parquet').to_pylist()
    assert rows[0]['content'] == clean.content
    assert rows[0]['content_sha256'] == clean.content_sha256
    with pytest.raises(FileExistsError):
        prepare_delta(base, [], output, source_dir=raw)
    stale = text + '\nSTALE'
    with sqlite3.connect(base) as db:
        db.execute('UPDATE contents SET content_zstd=?,content_sha256=? WHERE document_id=1',
                   (zstandard.ZstdCompressor().compress(stale.encode()), hashlib.sha256(stale.encode()).hexdigest()))
    with pytest.raises(ValueError, match='raw_parquet_base_mismatch'):
        prepare_delta(base, inventory, tmp_path / 'stale', source_dir=raw)
