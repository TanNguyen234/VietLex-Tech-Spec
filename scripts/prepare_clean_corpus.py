"""Stage an explicit clean overlay; never overwrite the pinned source stores.

The Parquet and SQLite outputs contain changed documents only. Consumers must
apply this overlay to the pinned base; these are not full-corpus replacements.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import zstandard

from app.ingestion.content_store import SCHEMA, ContentStore
from app.ingestion.corpus_cleaning import clean_corpus_text, verify_reconstruction
from app.ingestion.legal_text import build_sparse_text, normalize_legal_text


def _raw_rows(inventory: list[dict], source_dir: Path):
    shards = {}
    for entry in inventory:
        shard = entry['shard']
        if Path(shard).name != shard:
            raise ValueError('unsafe_source_shard')
        rows = shards.setdefault(shard, {})
        position = entry['row_zero_based']
        if type(position) is not int or position < 0 or position in rows:
            raise ValueError('invalid_source_position')
        rows[position] = entry
    for shard, wanted in sorted(shards.items()):
        position = 0
        found = 0
        for batch in pq.ParquetFile(source_dir / shard).iter_batches(batch_size=16, columns=['id','content']):
            for row in batch.to_pylist():
                entry = wanted.get(position)
                if entry is not None:
                    if row['id'] != entry['document_id']:
                        raise ValueError('raw_parquet_document_id_mismatch')
                    raw = row['content']
                    if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != entry['raw_sha256']:
                        raise ValueError('raw_parquet_hash_mismatch')
                    yield entry, raw
                    found += 1
                position += 1
            if found == len(wanted):
                break
        if found != len(wanted):
            raise ValueError('missing_raw_parquet_row')


def prepare_delta(base: Path, inventory: list[dict], output: Path, *, source_dir: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    if len({row['document_id'] for row in inventory}) != len(inventory):
        raise ValueError('duplicate_inventory_ids')
    if shutil.disk_usage(output.parent).free < 1_000_000_000:
        raise ValueError('local_disk_reserve_below_1GB')
    output.mkdir()
    store = ContentStore(base)
    compressor = zstandard.ZstdCompressor(level=3)
    counts = Counter()
    schema = pa.schema([
        ('id', pa.int64()), ('content', pa.string()), ('content_sha256', pa.string()),
        ('base_content_sha256', pa.string()), ('raw_parquet_sha256', pa.string()),
        ('source_shard', pa.string()), ('source_row', pa.int64()),
    ])
    # One document per row group bounds peak Python/Arrow memory.
    with sqlite3.connect(f'file:{base.resolve().as_posix()}?mode=ro', uri=True) as source, \
         sqlite3.connect(output / 'original-delta.sqlite3') as original, \
         sqlite3.connect(output / 'clean-delta.sqlite3') as clean, \
         pq.ParquetWriter(output / 'clean-delta.parquet', schema, compression='zstd') as parquet, \
         (output / 'changes.jsonl').open('x', encoding='utf-8') as changes:
        original.executescript(SCHEMA)
        clean.executescript(SCHEMA)
        for entry, raw_text in _raw_rows(inventory, source_dir):
            identifier = int(entry['document_id'])
            doc = store.get_many([identifier]).get(identifier)
            if doc is None:
                raise ValueError(f'missing_base_document:{identifier}')
            if normalize_legal_text(raw_text) != doc.content:
                raise ValueError(f'raw_parquet_base_mismatch:{identifier}')
            result = clean_corpus_text(doc.content)
            counts['scanned_signal_documents'] += 1
            if not verify_reconstruction(doc.content, result):
                raise ValueError(f'cleaning_integrity_failure:{identifier}')
            if not result.deletion_spans:
                counts['unchanged_signal_documents'] += 1
                continue
            metadata = source.execute('SELECT * FROM metadata WHERE document_id=?', (identifier,)).fetchone()
            content = source.execute('SELECT * FROM contents WHERE document_id=?', (identifier,)).fetchone()
            if content[3] != doc.content_sha256 or (content[4], content[5]) != (entry['shard'], entry['row_zero_based']):
                raise ValueError(f'base_provenance_drift:{identifier}')
            for target in (original, clean):
                target.execute('INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)', metadata)
            original.execute('INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)', content)
            body = result.cleaned_text.encode()
            cleaned_content = (identifier, compressor.compress(body), len(body), result.cleaned_sha256,
                               content[4], content[5], len(build_sparse_text(doc.metadata, result.cleaned_text).split()), content[7])
            clean.execute('INSERT INTO contents VALUES (?,?,?,?,?,?,?,?)', cleaned_content)
            parquet.write_table(pa.Table.from_pylist([{
                'id': identifier, 'content': result.cleaned_text, 'content_sha256': result.cleaned_sha256,
                'base_content_sha256': result.raw_sha256, 'raw_parquet_sha256': entry['raw_sha256'],
                'source_shard': entry['shard'], 'source_row': entry['row_zero_based'],
            }], schema=schema))
            changes.write(json.dumps({'document_id':identifier, 'base_sha256':result.raw_sha256,
                'cleaned_sha256':result.cleaned_sha256, 'raw_parquet_sha256':entry['raw_sha256'],
                'spans':[asdict(span) for span in result.deletion_spans]}, ensure_ascii=False) + '\n')
            counts['changed_documents'] += 1
            counts['removed_utf8_bytes'] += len(doc.content.encode()) - len(body)
            counts.update(span.rule_id for span in result.deletion_spans)
        for target in (original, clean):
            target.commit()
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('delta_sqlite_integrity_failure')
    checked = 0
    for batch in pq.ParquetFile(output / 'clean-delta.parquet').iter_batches(batch_size=1):
        row = batch.to_pylist()[0]
        saved = ContentStore(output / 'clean-delta.sqlite3').get_many([row['id']])[row['id']]
        if saved.content != row['content'] or saved.content_sha256 != row['content_sha256']:
            raise ValueError('delta_readback_mismatch')
        checked += 1
    report = dict(counts) | {'readback_verified_documents':checked,
        'representation':'changed-document overlay; base required; original source remains immutable',
        'remote_writes':False, 'legal_validity':'UNVERIFIED'}
    report['artifacts'] = {}
    for path in output.iterdir():
        if path.is_file():
            with path.open('rb') as stream:
                report['artifacts'][path.name] = {'bytes':path.stat().st_size,
                    'sha256':hashlib.file_digest(stream, 'sha256').hexdigest()}
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--scan-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    scan = json.loads((args.scan_dir / 'source-scan.json').read_text(encoding='utf-8'))
    if scan['totals']['scanned_rows'] != 518255:
        raise ValueError('incomplete_source_scan')
    rows = [json.loads(line) for line in (args.scan_dir / 'affected-source-rows.jsonl').read_text().splitlines()]
    if len(rows) != scan['totals']['affected_rows']:
        raise ValueError('inventory_count_mismatch')
    print(json.dumps(prepare_delta(args.base, rows, args.output, source_dir=args.source_dir), ensure_ascii=False))


if __name__ == '__main__':
    main()
