# Hugging Face Full-Corpus Qdrant Migration Implementation Plan

> **Implementation amendment (2026-07-30):** Dense ingestion and query
> embedding now use Qdrant Cloud Inference
> `intfloat/multilingual-e5-small` (384 dimensions). This replaces the measured
> Cloud Run BGE-M3 path, which was too slow for 518,255 documents. Batch 256 is
> the verified stable upload size; batch 512 produced repeated inference 500
> errors. The remaining BM25/PyVi and reranking design is unchanged.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the removed web-collection pipeline with a reproducible, resumable pipeline that downloads, validates, locally stores, indexes, and retrieves all 518,255 documents from the pinned `vohuutridung/vietnamese-legal-documents` dataset.

**Architecture:** Keep the complete pinned Parquet snapshot and a random-access Zstandard/SQLite content store in the project, while Qdrant stores exactly one FLOAT16 BGE-M3 vector plus one bounded BM25 sparse vector per source document. Runtime retrieval performs one Qdrant hybrid document search, resolves candidate texts locally, dynamically creates legal-structure-aware evidence chunks, applies a lexical bound, and reranks the remaining chunks with BGE-reranker-v2-M3.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic Settings, HTTPX, PyArrow, SQLite, Zstandard, PyVi, Qdrant Client 1.18+, BGE-M3 Cloud Run service, BGE-reranker-v2-M3 Cloud Run service, pytest, pytest-asyncio.

## Global Constraints

- Dataset repository is exactly `vohuutridung/vietnamese-legal-documents`.
- Dataset revision is exactly `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`.
- The metadata/content join key is integer `id`; row position is never a join key.
- A successful corpus contains exactly 518,255 unique metadata IDs and 518,255 unique content IDs.
- The knowledge collection is exactly `vietlex_legal_documents_v1`.
- Qdrant contains exactly one point per source document, never pre-expanded article chunks.
- Dense vectors are named `dense`, use BGE-M3, have 1024 dimensions, cosine distance, FLOAT16 storage, and on-disk vectors.
- Sparse vectors are named `bm25`, use identical document/query token normalization, Qdrant IDF, and an on-disk sparse index.
- Qdrant payloads exclude full document content.
- Full content is stored locally as independently compressed Zstandard blobs in SQLite.
- Default semantic-cache similarity remains `0.96`, and cache identity includes the pinned corpus revision.
- MongoDB remains limited to conversations, feedback, evaluation, and administrative logs.
- Production code has no mock or placeholder fallback for embedding, reranking, Qdrant, parsing, or content resolution.
- Secrets are loaded only through `app/config.py`; manifests, checkpoints, reports, tests, README, and logs contain no secret values.
- No Qdrant collection is deleted before local validation, unit tests, real embedding/reranker smoke tests, and a temporary-collection Qdrant smoke test pass.
- The destructive reset accepts only the observed set `test_inference_collection`, `vietlex_knowledge_base`, `vietlex_laws_crawler_kb`, and `vietlex_semantic_cache`; an unexpected collection aborts the reset for review.
- A permanent preparation/embedding failure prevents the final 518,255-point success state; it is audited and must be fixed before resume.
- The third-party corpus is informational, is not an official legal database, does not establish current legal effect, and must be checked against current official sources or qualified counsel.
- Generated dataset, content-store, checkpoint, and benchmark files remain outside Git.
- Commit steps are conditional on explicit user authorization, as required by `AGENTS.md`; until authorized, leave changes uncommitted.

---

## File and Responsibility Map

- `app/config.py`: all corpus, Qdrant, batching, local-path, and secret-backed settings.
- `app/ingestion/dataset_snapshot.py`: pinned file list, resumable direct downloads, checksums, manifest, and disk preflight.
- `app/ingestion/legal_text.py`: normalization, outline extraction, deterministic IDs, retrieval text, legal/fallback chunking.
- `app/ingestion/sparse_encoder.py`: stable Vietnamese BM25-compatible document/query sparse encoding.
- `app/ingestion/content_store.py`: streaming Parquet import, ID validation, Zstandard/SQLite storage, audit statistics, random access.
- `app/ingestion/embedding_client.py`: bounded BGE-M3 batch requests, retry policy, adaptive concurrency, dimension validation.
- `app/ingestion/checkpoint.py`: durable batch state, failures, throughput metrics, and resume.
- `app/ingestion/qdrant_store.py`: collection schema, guarded reset, point construction, bulk upload, optimizer restoration, verification.
- `app/ingestion/hf_pipeline.py`: phase orchestration and the single supported CLI.
- `app/services/clients.py`: application-scoped HTTPX and Qdrant clients.
- `app/services/retrieval.py`: hybrid document retrieval, local resolution, lexical prefilter, remote reranking.
- `app/services/rag_pipeline.py`: query rewrite, evidence handoff, grounded answer generation, and latency reporting.
- `app/services/semantic_cache.py`: 1024-dimensional, revision-aware semantic cache.
- `app/main.py`: initialize and close application-scoped retrieval clients.
- `app/templates/index.html`: prominent source-quality/legal-information warning.
- `tests/ingestion/`: unit coverage for every preparation and indexing boundary.
- `tests/services/`: runtime retrieval, cache, client-lifecycle, and fail-closed tests.
- `docs/huggingface-ingestion-runbook.md`: exact commands, recovery, reports, capacity, and verification.

---

### Task 1: Lock Configuration, Dependencies, Paths, and Secret Defaults

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `app/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.DATASET_REPOSITORY`, `Settings.DATASET_REVISION`, `Settings.DATASET_ROOT`, `Settings.CONTENT_STORE_PATH`, `Settings.INGESTION_STATE_PATH`, `Settings.LEGAL_COLLECTION_NAME`, batching limits, vector names, and optimizer settings.
- Consumes: no migration-specific interfaces.

- [ ] **Step 1: Write failing configuration and secret-default tests**

```python
# tests/test_config.py
from pathlib import Path

from app.config import Settings


def test_migration_defaults_are_pinned_and_capacity_bounded() -> None:
    settings = Settings(_env_file=None)
    assert settings.DATASET_REPOSITORY == "vohuutridung/vietnamese-legal-documents"
    assert settings.DATASET_REVISION == "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
    assert settings.EXPECTED_DOCUMENT_COUNT == 518_255
    assert settings.LEGAL_COLLECTION_NAME == "vietlex_legal_documents_v1"
    assert settings.DENSE_VECTOR_NAME == "dense"
    assert settings.SPARSE_VECTOR_NAME == "bm25"
    assert settings.DENSE_VECTOR_SIZE == 1024
    assert settings.CONTENT_STORE_PATH == Path("data/huggingface/content_store.sqlite3")


def test_secret_defaults_never_contain_credentials() -> None:
    settings = Settings(_env_file=None)
    assert settings.QDRANT_API_KEY is None
    assert settings.EMBEDDING_SERVICE_API_KEY is None
    assert settings.LITELLM_MASTER_KEY is None
    assert settings.COHERE_API_KEY is None
    assert settings.MONGO_URL is None
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL because the corpus settings do not exist and `LITELLM_MASTER_KEY` still has a non-empty default.

- [ ] **Step 3: Add direct dependencies and exact configuration fields**

```text
# requirements.txt additions/replacements
httpx>=0.27.0,<1.0
pyarrow>=17.0.0
zstandard>=0.23.0
qdrant-client>=1.18.0,<2.0
pytest-asyncio>=0.23.0
```

```python
# app/config.py fields
from pathlib import Path

LITELLM_MASTER_KEY: Optional[str] = None
DATASET_REPOSITORY: str = "vohuutridung/vietnamese-legal-documents"
DATASET_REVISION: str = "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
EXPECTED_DOCUMENT_COUNT: int = 518_255
DATASET_ROOT: Path = Path("data/huggingface")
CONTENT_STORE_PATH: Path = Path("data/huggingface/content_store.sqlite3")
INGESTION_STATE_PATH: Path = Path("data/huggingface/ingestion_state.sqlite3")
INGESTION_REPORT_PATH: Path = Path("data/huggingface/ingestion_report.json")
LEGAL_COLLECTION_NAME: str = "vietlex_legal_documents_v1"
SEMANTIC_CACHE_COLLECTION_NAME: str = "vietlex_semantic_cache"
DENSE_VECTOR_NAME: str = "dense"
SPARSE_VECTOR_NAME: str = "bm25"
DENSE_VECTOR_SIZE: int = 1024
EMBED_MAX_DOCUMENTS: int = 32
EMBED_MAX_CHARACTERS: int = 180_000
EMBED_CONCURRENCY: int = 8
UPLOAD_BATCH_SIZE: int = 256
UPLOAD_PARALLELISM: int = 4
RETRIEVAL_DOCUMENT_LIMIT: int = 24
LEXICAL_CHUNK_LIMIT: int = 64
RERANK_TOP_K: int = 3
```

Add `data/huggingface/` to `.gitignore`. Add the same non-secret setting names to `.env.example`, using empty values for every secret and the pinned defaults for non-secret settings.

- [ ] **Step 4: Run tests and static secret scans**

Run:

```powershell
python -m pytest tests/test_config.py -q
rg -n "default_litellm_master_key|EMBEDDING_SERVICE_API_KEY:\s*Optional\[str\]\s*=\s*\"" app README.md .env.example
```

Expected: tests PASS and `rg` returns no matches.

- [ ] **Step 5: Commit only if explicit authorization has been given**

```powershell
git add requirements.txt .gitignore .env.example app/config.py tests/test_config.py
git commit -m "chore: lock legal corpus configuration"
```

---

### Task 2: Download a Pinned Snapshot with Resume and Integrity Manifest

**Files:**
- Create: `app/ingestion/dataset_snapshot.py`
- Create: `tests/ingestion/test_dataset_snapshot.py`

**Interfaces:**
- Produces: `REQUIRED_DATASET_FILES`, `snapshot_directory(settings) -> Path`, `download_snapshot(settings, client=None) -> SnapshotManifest`, `verify_snapshot(path, expected_count=13) -> SnapshotManifest`.
- Consumes: dataset repository, revision, root, and expected document count from `Settings`.

- [ ] **Step 1: Write failing tests for pinning, range resume, checksum, and atomic rename**

```python
# tests/ingestion/test_dataset_snapshot.py
import hashlib
from pathlib import Path

import httpx
import pytest

from app.ingestion.dataset_snapshot import (
    RequiredDatasetFile,
    download_required_file,
    snapshot_directory,
)
from app.config import Settings


def test_snapshot_directory_contains_exact_revision(tmp_path: Path) -> None:
    settings = Settings(DATASET_ROOT=tmp_path, _env_file=None)
    assert snapshot_directory(settings) == (
        tmp_path
        / "vohuutridung__vietnamese-legal-documents"
        / settings.DATASET_REVISION
    )


@pytest.mark.asyncio
async def test_download_resumes_part_file_and_writes_verified_target(tmp_path: Path) -> None:
    payload = b"0123456789"
    target = tmp_path / "content" / "part.parquet"
    target.parent.mkdir(parents=True)
    target.with_suffix(".parquet.part").write_bytes(payload[:4])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=4-"
        return httpx.Response(
            206,
            content=payload[4:],
            headers={"Content-Range": "bytes 4-9/10"},
        )

    required = RequiredDatasetFile("content/part.parquet", 10)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        downloaded = await download_required_file(
            client,
            "https://example.invalid/pinned/content/part.parquet",
            target,
            required,
        )

    assert target.read_bytes() == payload
    assert not target.with_suffix(".parquet.part").exists()
    assert downloaded.sha256 == hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/ingestion/test_dataset_snapshot.py -q`

Expected: FAIL with `ModuleNotFoundError: app.ingestion.dataset_snapshot`.

- [ ] **Step 3: Implement the exact pinned file set and resumable downloader**

```python
# app/ingestion/dataset_snapshot.py
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

from app.config import Settings


CONTENT_FILES = tuple(
    f"content/data-{index:05d}-of-00011.parquet" for index in range(11)
)
REQUIRED_PATHS = ("README.md", "metadata/data-00000-of-00001.parquet", *CONTENT_FILES)


@dataclass(frozen=True)
class RequiredDatasetFile:
    path: str
    expected_size: int


@dataclass(frozen=True)
class DownloadedFile:
    path: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class SnapshotManifest:
    repository: str
    revision: str
    completed_at: str
    files: tuple[DownloadedFile, ...]


def snapshot_directory(settings: Settings) -> Path:
    slug = settings.DATASET_REPOSITORY.replace("/", "__")
    return settings.DATASET_ROOT / slug / settings.DATASET_REVISION


def resolve_url(settings: Settings, path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{settings.DATASET_REPOSITORY}"
        f"/resolve/{settings.DATASET_REVISION}/{path}?download=true"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
```

`download_required_file` must send `Range: bytes=<part-size>-` when a `.part` exists, require HTTP 206 for resumed requests, validate `Content-Range`, fsync the completed file, compare exact expected size, compute SHA-256, then use `os.replace(part_path, target)`. Retry only 408/429/5xx and transport/timeouts with exponential delay `min(60, 2**attempt) + random.uniform(0, 1)`.

`download_snapshot` must:

1. issue a followed-redirect HEAD for every pinned URL;
2. derive expected bytes from `x-linked-size` or `content-length`;
3. require free bytes greater than all missing bytes plus 1 GiB;
4. download files sequentially so at most one large `.part` is active;
5. atomically write `manifest.json` with repository, revision, URL, bytes, local SHA-256, UTC completion time, and downloader schema version;
6. reject any manifest whose repository, revision, file set, size, or local hash differs.

- [ ] **Step 4: Run downloader tests and a no-download URL audit**

Run:

```powershell
python -m pytest tests/ingestion/test_dataset_snapshot.py -q
python -c "from app.config import get_settings; from app.ingestion.dataset_snapshot import REQUIRED_PATHS, resolve_url; s=get_settings(); assert len(REQUIRED_PATHS)==13; assert all(s.DATASET_REVISION in resolve_url(s,p) for p in REQUIRED_PATHS)"
```

Expected: PASS; exactly 13 required files and every URL contains the full pinned revision.

- [ ] **Step 5: Commit only if explicitly authorized**

```powershell
git add app/ingestion/dataset_snapshot.py tests/ingestion/test_dataset_snapshot.py
git commit -m "feat: add resumable pinned dataset download"
```

---

### Task 3: Implement Legal Text Normalization, Chunking, Retrieval Text, and Sparse Parity

**Files:**
- Create: `app/ingestion/legal_text.py`
- Create: `app/ingestion/sparse_encoder.py`
- Create: `tests/ingestion/test_legal_text.py`
- Create: `tests/ingestion/test_sparse_encoder.py`

**Interfaces:**
- Produces: `DocumentMetadata`, `EvidenceChunk`, `normalize_legal_text`, `build_dense_text`, `build_sparse_text`, `chunk_document`, `deterministic_point_id`, and `SparseEncoder`.
- Consumes: normalized dataset metadata fields.

- [ ] **Step 1: Write failing legal-structure, fallback, bound, UUID, and sparse-parity tests**

```python
# tests/ingestion/test_legal_text.py
from app.ingestion.legal_text import (
    DocumentMetadata,
    build_dense_text,
    chunk_document,
    deterministic_point_id,
)


META = DocumentMetadata(
    document_id=42,
    document_number="12/2026/NĐ-CP",
    title="Nghị định thử nghiệm",
    source_url="https://example.invalid/42",
    legal_type="Nghị định",
    legal_sectors="Hành chính",
    issuing_authority="Chính phủ",
    issuance_date="2026-01-02",
)


def test_article_chunk_preserves_heading_ancestry_and_citation() -> None:
    text = "Chương I\nQUY ĐỊNH CHUNG\nĐiều 1. Phạm vi\n1. Nội dung thứ nhất.\n2. Nội dung thứ hai."
    chunks = chunk_document(META, text, max_tokens=40, overlap_tokens=5)
    assert chunks[0].article == "Điều 1"
    assert "Chương I" in chunks[0].heading_path
    assert chunks[0].citation.startswith("12/2026/NĐ-CP, Điều 1")


def test_paragraph_fallback_is_bounded_and_nonempty() -> None:
    text = "\n\n".join(f"Đoạn văn hành chính số {index} có nội dung." for index in range(80))
    chunks = chunk_document(META, text, max_tokens=30, overlap_tokens=5)
    assert len(chunks) > 1
    assert all(0 < chunk.token_count <= 30 for chunk in chunks)


def test_dense_text_and_point_id_are_deterministic() -> None:
    text = "Điều 1. A\n" + ("nội dung " * 10_000) + "\nĐiều 99. Z"
    first = build_dense_text(META, text, max_tokens=256)
    second = build_dense_text(META, text, max_tokens=256)
    assert first == second
    assert len(first.split()) <= 256
    assert deterministic_point_id("repo", "revision", 42) == deterministic_point_id(
        "repo", "revision", 42
    )
```

```python
# tests/ingestion/test_sparse_encoder.py
from app.ingestion.sparse_encoder import SparseEncoder


def test_document_and_query_use_identical_term_ids() -> None:
    encoder = SparseEncoder(average_document_length=100.0)
    document = encoder.encode_document("thuế thu nhập thuế")
    query = encoder.encode_query("thuế thu nhập")
    assert set(query.indices).issubset(set(document.indices))
    assert document.indices == sorted(document.indices)


def test_sparse_text_limit_bounds_index_growth() -> None:
    encoder = SparseEncoder(average_document_length=100.0, max_terms=32)
    vector = encoder.encode_document(" ".join(f"từ{index}" for index in range(500)))
    assert len(vector.indices) <= 32
    assert len(vector.indices) == len(vector.values)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/ingestion/test_legal_text.py tests/ingestion/test_sparse_encoder.py -q`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement deterministic legal text interfaces**

```python
# core interfaces in app/ingestion/legal_text.py
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5


@dataclass(frozen=True)
class DocumentMetadata:
    document_id: int
    document_number: str
    title: str
    source_url: str
    legal_type: str
    legal_sectors: str
    issuing_authority: str
    issuance_date: str | None


@dataclass(frozen=True)
class EvidenceChunk:
    document_id: int
    document_number: str
    title: str
    source_url: str
    heading_path: str
    article: str | None
    clause: str | None
    citation: str
    text: str
    token_count: int

    def formatted_context(self) -> str:
        return (
            f"[{self.citation}]\n"
            f"Nguồn: {self.source_url}\n"
            f"Tiêu đề: {self.title}\n{self.text}"
        )


def deterministic_point_id(repository: str, revision: str, document_id: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"{repository}@{revision}#{document_id}")
```

Normalize Unicode to NFC, replace non-breaking spaces, normalize line endings, collapse horizontal whitespace, and retain paragraph boundaries. Detect headings with anchored, case-insensitive expressions for `Chương`, `Mục`, `Tiểu mục`, `Điều`, and numeric clauses. Article chunks inherit the active chapter/section/article/clause path; content without article headings uses paragraph windows. A single overlong paragraph is split by sentence boundary, then by bounded token windows as the final deterministic fallback.

`build_dense_text` must concatenate metadata, the leading substantive text, and a de-duplicated outline collected across the entire document, then enforce both the configured token and character caps. `build_sparse_text` must use metadata plus outline plus bounded substantive terms with a default limit of 2,048 normalized terms.

- [ ] **Step 4: Implement stable BM25-compatible sparse weights**

```python
# app/ingestion/sparse_encoder.py
import hashlib
import math
from collections import Counter
from dataclasses import dataclass

from pyvi import ViTokenizer
from qdrant_client.models import SparseVector


def normalized_terms(text: str) -> list[str]:
    segmented = ViTokenizer.tokenize(text.lower())
    return [term for term in segmented.split() if any(char.isalnum() for char in term)]


def stable_term_id(term: str) -> int:
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF


@dataclass(frozen=True)
class SparseEncoder:
    average_document_length: float
    max_terms: int = 2_048
    k1: float = 1.2
    b: float = 0.75

    def encode_document(self, text: str) -> SparseVector:
        terms = normalized_terms(text)[: self.max_terms]
        counts = Counter(terms)
        length = max(1, len(terms))
        pairs = []
        for term, frequency in counts.items():
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * length / max(1.0, self.average_document_length)
            )
            weight = frequency * (self.k1 + 1) / denominator
            pairs.append((stable_term_id(term), float(weight)))
        pairs.sort()
        return SparseVector(
            indices=[item[0] for item in pairs],
            values=[item[1] for item in pairs],
        )

    def encode_query(self, text: str) -> SparseVector:
        counts = Counter(normalized_terms(text)[: self.max_terms])
        pairs = sorted((stable_term_id(term), 1.0 + math.log(freq)) for term, freq in counts.items())
        return SparseVector(
            indices=[item[0] for item in pairs],
            values=[float(item[1]) for item in pairs],
        )
```

Qdrant supplies corpus IDF through `Modifier.IDF`; these values supply stable term-frequency saturation and document-length normalization.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/ingestion/test_legal_text.py tests/ingestion/test_sparse_encoder.py -q`

Expected: PASS.

- [ ] **Step 6: Commit only if explicitly authorized**

```powershell
git add app/ingestion/legal_text.py app/ingestion/sparse_encoder.py tests/ingestion/test_legal_text.py tests/ingestion/test_sparse_encoder.py
git commit -m "feat: add legal chunking and sparse encoding"
```

---

### Task 4: Build the Streaming Zstandard/SQLite Content Store and Join Audit

**Files:**
- Create: `app/ingestion/content_store.py`
- Create: `tests/ingestion/test_content_store.py`

**Interfaces:**
- Produces: `BuildReport`, `StoredDocument`, `build_content_store(snapshot_path, database_path, expected_count) -> BuildReport`, and `ContentStore.get_many(document_ids)`.
- Consumes: `normalize_legal_text`, `build_sparse_text`, `normalized_terms`, and verified Parquet snapshot files.

- [ ] **Step 1: Write a failing out-of-order join, compression, and quality test**

```python
# tests/ingestion/test_content_store.py
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.ingestion.content_store import ContentStore, build_content_store


def test_store_joins_by_id_and_round_trips_compressed_content(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    (snapshot / "metadata").mkdir(parents=True)
    (snapshot / "content").mkdir()
    pq.write_table(
        pa.table(
            {
                "id": [2, 1],
                "document_number": ["02/QĐ", "01/QĐ"],
                "title": ["Hai", "Một"],
                "url": ["https://example/2", "https://example/1"],
                "legal_type": ["Quyết định", "Quyết định"],
                "legal_sectors": ["A", "B"],
                "issuing_authority": ["Bộ B", "Bộ A"],
                "issuance_date": ["02/01/2026", "01/01/2026"],
                "signers": ["", ""],
            }
        ),
        snapshot / "metadata" / "data-00000-of-00001.parquet",
    )
    pq.write_table(
        pa.table({"id": [1, 2], "content": ["Điều 1. Nội dung một", "Điều 2. Nội dung hai"]}),
        snapshot / "content" / "data-00000-of-00011.parquet",
    )

    report = build_content_store(snapshot, tmp_path / "store.sqlite3", expected_count=2)
    documents = ContentStore(tmp_path / "store.sqlite3").get_many([1, 2])

    assert report.joined_count == 2
    assert documents[1].title == "Một"
    assert documents[1].content == "Điều 1. Nội dung một"
    assert documents[1].content_sha256 != documents[2].content_sha256
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/ingestion/test_content_store.py -q`

Expected: FAIL because `content_store` is absent.

- [ ] **Step 3: Implement schema, transactional streaming, and independent compression**

```sql
CREATE TABLE metadata (
    document_id INTEGER PRIMARY KEY,
    document_number TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    legal_type TEXT NOT NULL,
    legal_sectors TEXT NOT NULL,
    issuing_authority TEXT NOT NULL,
    issuance_date TEXT,
    signers TEXT NOT NULL,
    quality_flags TEXT NOT NULL
);
CREATE TABLE contents (
    document_id INTEGER PRIMARY KEY,
    content_zstd BLOB NOT NULL,
    content_bytes INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_shard TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    sparse_token_count INTEGER NOT NULL,
    quality_flags TEXT NOT NULL
);
CREATE TABLE build_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Use `pyarrow.parquet.ParquetFile.iter_batches(batch_size=2048)`, not pandas and not `load_dataset()`. Use SQLite `journal_mode=WAL`, `synchronous=NORMAL`, `temp_store=MEMORY`, and `executemany` inside one transaction per record batch. Compress each normalized UTF-8 content value with `zstandard.ZstdCompressor(level=3)`.

Quality flags are a sorted JSON array drawn only from:

```python
QUALITY_FLAGS = {
    "missing_document_number",
    "missing_title",
    "missing_source_url",
    "invalid_issuance_date",
    "empty_content",
    "encoding_damage",
    "abnormal_length",
    "duplicate_content_hash",
}
```

Normalize dates from `DD/MM/YYYY` to ISO `YYYY-MM-DD`; invalid non-empty dates receive `invalid_issuance_date` and a null normalized date. After import, run SQL checks for duplicate IDs, metadata without content, content without metadata, empty content, and total count. Any count mismatch raises `DatasetIntegrityError` before a content-store success marker is written.

The final `BuildReport` includes metadata count, content count, joined count, duplicate hash count, total compressed/uncompressed bytes, compression ratio, average sparse document length, quality-flag counts, source shard row counts, schema version, repository, revision, and wall time.

- [ ] **Step 4: Implement bounded random access and hash verification**

```python
@dataclass(frozen=True)
class StoredDocument:
    metadata: DocumentMetadata
    content: str
    content_sha256: str
    content_store_key: str
    quality_flags: tuple[str, ...]


class ContentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._decompressor = zstandard.ZstdDecompressor()

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        if not document_ids:
            return {}
        placeholders = ",".join("?" for _ in document_ids)
        sql = (
            "SELECT m.*, c.content_zstd, c.content_sha256, c.quality_flags "
            "FROM metadata m JOIN contents c USING(document_id) "
            f"WHERE document_id IN ({placeholders})"
        )
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
            rows = connection.execute(sql, document_ids).fetchall()
        return self._decode_and_verify(rows)
```

`_decode_and_verify` must recompute SHA-256 after decompression and raise `ContentIntegrityError` on mismatch. `content_store_key` is the decimal document ID and is the only locator stored in Qdrant.

- [ ] **Step 5: Run content-store tests**

Run: `python -m pytest tests/ingestion/test_content_store.py -q`

Expected: PASS, including mismatch/duplicate/missing-join cases added beside the main test.

- [ ] **Step 6: Commit only if explicitly authorized**

```powershell
git add app/ingestion/content_store.py tests/ingestion/test_content_store.py
git commit -m "feat: build verified compressed legal content store"
```

---

### Task 5: Add Bounded Embedding, Adaptive Batches, and Durable Checkpoints

**Files:**
- Create: `app/ingestion/embedding_client.py`
- Create: `app/ingestion/checkpoint.py`
- Create: `tests/ingestion/test_embedding_client.py`
- Create: `tests/ingestion/test_checkpoint.py`

**Interfaces:**
- Produces: `AdaptiveBatcher.iter_batches`, `BgeEmbeddingClient.embed_batch`, `BgeEmbeddingClient.embed_many`, and `CheckpointStore`.
- Consumes: shared HTTPX client, embedding URL/key, 1024 dimension, concurrency, document and character caps.

- [ ] **Step 1: Write failing batch-cap, retry, dimension, and resume tests**

```python
# tests/ingestion/test_embedding_client.py
import httpx
import pytest

from app.ingestion.embedding_client import AdaptiveBatcher, BgeEmbeddingClient


def test_batcher_honors_document_and_character_caps() -> None:
    batches = list(
        AdaptiveBatcher(max_documents=2, max_characters=5).iter_batches(
            [(1, "aa"), (2, "bbb"), (3, "cccc")]
        )
    )
    assert [[item[0] for item in batch] for batch in batches] == [[1, 2], [3]]


@pytest.mark.asyncio
async def test_embedding_client_retries_transient_response_and_validates_dimension() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"embeddings": [[0.0, 1.0], [1.0, 0.0]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = BgeEmbeddingClient(
            client=client,
            url="https://example.invalid/embed",
            api_key=None,
            dimensions=2,
            concurrency=2,
        )
        vectors = await service.embed_batch(["a", "b"])

    assert attempts == 2
    assert vectors == [[0.0, 1.0], [1.0, 0.0]]
```

```python
# tests/ingestion/test_checkpoint.py
from pathlib import Path

from app.ingestion.checkpoint import CheckpointStore


def test_completed_batches_are_skipped_on_resume(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state.sqlite3", revision="rev")
    store.mark_completed(batch_id=0, first_id=1, last_id=256, point_count=256, seconds=2.0)
    assert store.completed_batch_ids() == {0}
    assert store.next_incomplete([0, 1, 2]) == 1
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/ingestion/test_embedding_client.py tests/ingestion/test_checkpoint.py -q`

Expected: FAIL because the modules are absent.

- [ ] **Step 3: Implement bounded async embedding without serial document calls**

```python
class AdaptiveBatcher:
    def __init__(self, max_documents: int, max_characters: int) -> None:
        self.max_documents = max_documents
        self.max_characters = max_characters

    def iter_batches(self, items: Iterable[tuple[int, str]]) -> Iterator[list[tuple[int, str]]]:
        batch: list[tuple[int, str]] = []
        characters = 0
        for item in items:
            item_size = len(item[1])
            if batch and (
                len(batch) >= self.max_documents
                or characters + item_size > self.max_characters
            ):
                yield batch
                batch = []
                characters = 0
            batch.append(item)
            characters += item_size
        if batch:
            yield batch
```

`BgeEmbeddingClient.embed_batch` sends exactly `{"inputs": texts, "normalize": true}`, applies the Bearer header only when configured, retries 408/429/5xx/timeouts with jitter, validates response count and every vector dimension, and never fabricates a vector. `embed_many` runs batches through an `asyncio.Semaphore`, keeps output ordered by document ID, and halves active concurrency after repeated throttling; it increases by one only after ten consecutive successful requests.

- [ ] **Step 4: Implement checkpoint and failure schemas**

```sql
CREATE TABLE batches (
    revision TEXT NOT NULL,
    batch_id INTEGER NOT NULL,
    first_document_id INTEGER NOT NULL,
    last_document_id INTEGER NOT NULL,
    point_count INTEGER NOT NULL,
    seconds REAL NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (revision, batch_id)
);
CREATE TABLE failures (
    revision TEXT NOT NULL,
    document_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (revision, document_id, stage)
);
CREATE TABLE metrics (
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);
```

All writes use transactions. Error messages are sanitized to remove authorization headers and configured secret values. A batch is marked complete only after Qdrant confirms upload success.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/ingestion/test_embedding_client.py tests/ingestion/test_checkpoint.py -q`

Expected: PASS.

- [ ] **Step 6: Commit only if explicitly authorized**

```powershell
git add app/ingestion/embedding_client.py app/ingestion/checkpoint.py tests/ingestion/test_embedding_client.py tests/ingestion/test_checkpoint.py
git commit -m "feat: add bounded embedding and ingestion checkpoints"
```

---

### Task 6: Define the Capacity-Bounded Qdrant Schema and Guarded Bulk Upload

**Files:**
- Replace: `app/ingestion/indexer.py`
- Delete: `app/ingestion/qdrant_indexer.py`
- Delete: `app/ingestion/vlegal_indexer.py`
- Create: `app/ingestion/qdrant_store.py`
- Create: `tests/ingestion/test_qdrant_store.py`

**Interfaces:**
- Produces: `EXPECTED_OLD_COLLECTIONS`, `validate_reset_scope`, `create_legal_collection`, `restore_production_indexing`, `build_point`, `upload_point_batch`, and `verify_collection`.
- Consumes: deterministic UUID, dense/sparse vectors, `StoredDocument`, `CheckpointStore`, and Qdrant settings.

- [ ] **Step 1: Write failing schema, payload, and destructive-scope tests**

```python
# tests/ingestion/test_qdrant_store.py
import pytest
from qdrant_client import models

from app.ingestion.qdrant_store import (
    EXPECTED_OLD_COLLECTIONS,
    build_collection_arguments,
    validate_reset_scope,
)


def test_collection_is_float16_on_disk_with_idf_sparse_index() -> None:
    arguments = build_collection_arguments(shard_number=2)
    dense = arguments["vectors_config"]["dense"]
    sparse = arguments["sparse_vectors_config"]["bm25"]
    assert dense.size == 1024
    assert dense.distance == models.Distance.COSINE
    assert dense.datatype == models.Datatype.FLOAT16
    assert dense.on_disk is True
    assert sparse.modifier == models.Modifier.IDF
    assert sparse.index.on_disk is True
    assert arguments["on_disk_payload"] is True


def test_reset_scope_aborts_on_unexpected_collection() -> None:
    with pytest.raises(RuntimeError, match="unexpected"):
        validate_reset_scope(EXPECTED_OLD_COLLECTIONS | {"unrelated_business_data"})
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/ingestion/test_qdrant_store.py -q`

Expected: FAIL because `qdrant_store` is absent.

- [ ] **Step 3: Implement the collection arguments and guarded reset**

```python
EXPECTED_OLD_COLLECTIONS = frozenset(
    {
        "test_inference_collection",
        "vietlex_knowledge_base",
        "vietlex_laws_crawler_kb",
        "vietlex_semantic_cache",
    }
)


def validate_reset_scope(existing: set[str]) -> tuple[str, ...]:
    unexpected = existing - EXPECTED_OLD_COLLECTIONS
    if unexpected:
        raise RuntimeError(f"Refusing destructive reset; unexpected collections: {sorted(unexpected)}")
    return tuple(sorted(existing))


def build_collection_arguments(shard_number: int) -> dict[str, object]:
    return {
        "vectors_config": {
            "dense": models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
                datatype=models.Datatype.FLOAT16,
                on_disk=True,
            )
        },
        "sparse_vectors_config": {
            "bm25": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=True),
                modifier=models.Modifier.IDF,
            )
        },
        "shard_number": shard_number,
        "on_disk_payload": True,
        "hnsw_config": models.HnswConfigDiff(m=0, on_disk=True),
        "optimizers_config": models.OptimizersConfigDiff(indexing_threshold=0),
    }
```

`reset_and_create` must list current collections immediately before mutation, pass the names through `validate_reset_scope`, require `allow_destructive=True`, delete only the returned names, and then create `vietlex_legal_documents_v1`. Try two shards first; if the server explicitly rejects shard count before creating the collection, retry once with one shard and record that fallback in the report.

Create payload indexes before upload:

```python
PAYLOAD_INDEXES = {
    "document_id": models.PayloadSchemaType.INTEGER,
    "document_number": models.PayloadSchemaType.KEYWORD,
    "legal_type": models.PayloadSchemaType.KEYWORD,
    "issuing_authority": models.PayloadSchemaType.KEYWORD,
    "issuance_date": models.PayloadSchemaType.DATETIME,
    "dataset_revision": models.PayloadSchemaType.KEYWORD,
}
```

- [ ] **Step 4: Implement minimal payload and parallel upload**

```python
def build_point(document, dense_vector, sparse_vector, settings) -> models.PointStruct:
    return models.PointStruct(
        id=deterministic_point_id(
            settings.DATASET_REPOSITORY,
            settings.DATASET_REVISION,
            document.metadata.document_id,
        ),
        vector={
            settings.DENSE_VECTOR_NAME: dense_vector,
            settings.SPARSE_VECTOR_NAME: sparse_vector,
        },
        payload={
            "document_id": document.metadata.document_id,
            "document_number": document.metadata.document_number,
            "title": document.metadata.title,
            "legal_type": document.metadata.legal_type,
            "legal_sectors": document.metadata.legal_sectors,
            "issuing_authority": document.metadata.issuing_authority,
            "issuance_date": document.metadata.issuance_date,
            "source_url": document.metadata.source_url,
            "dataset_repository": settings.DATASET_REPOSITORY,
            "dataset_revision": settings.DATASET_REVISION,
            "content_sha256": document.content_sha256,
            "content_store_key": str(document.metadata.document_id),
            "quality_flags": list(document.quality_flags),
        },
    )
```

`upload_point_batch` calls:

```python
client.upload_points(
    collection_name=settings.LEGAL_COLLECTION_NAME,
    points=points,
    batch_size=settings.UPLOAD_BATCH_SIZE,
    parallel=settings.UPLOAD_PARALLELISM,
    max_retries=5,
    wait=True,
)
```

After the final batch, call `update_collection` with `HnswConfigDiff(m=16, ef_construct=128, on_disk=True)` and `OptimizersConfigDiff(indexing_threshold=20_000, max_optimization_threads=2)`. Poll collection status with bounded intervals until it is green or the configured timeout expires.

- [ ] **Step 5: Run Qdrant store tests**

Run: `python -m pytest tests/ingestion/test_qdrant_store.py -q`

Expected: PASS, including point payload exclusion of full content and idempotent point-ID tests.

- [ ] **Step 6: Commit only if explicitly authorized**

```powershell
git add app/ingestion/indexer.py app/ingestion/qdrant_store.py tests/ingestion/test_qdrant_store.py
git add -u app/ingestion/qdrant_indexer.py app/ingestion/vlegal_indexer.py
git commit -m "feat: add guarded capacity-bounded qdrant upload"
```

---

### Task 7: Orchestrate Prepare, Smoke, Benchmark, Full Resume, and Reconciliation

**Files:**
- Create: `app/ingestion/hf_pipeline.py`
- Create: `tests/ingestion/test_hf_pipeline.py`

**Interfaces:**
- Produces: CLI phases `download`, `prepare`, `smoke`, `benchmark`, `full`, and `verify`; `run_full(settings, allow_destructive) -> IngestionReport`.
- Consumes: all Tasks 1–6 interfaces.

- [ ] **Step 1: Write failing preflight-order and resume tests**

```python
# tests/ingestion/test_hf_pipeline.py
import pytest

from app.ingestion.hf_pipeline import PreflightResult, assert_destructive_preflight


def test_destructive_preflight_requires_every_local_and_real_service_gate() -> None:
    result = PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        unit_tests_passed=True,
        embedding_smoke_passed=True,
        reranker_smoke_passed=False,
        qdrant_smoke_passed=True,
        joined_count=518_255,
    )
    with pytest.raises(RuntimeError, match="reranker"):
        assert_destructive_preflight(result)


def test_full_success_requires_exact_remote_count() -> None:
    result = PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        unit_tests_passed=True,
        embedding_smoke_passed=True,
        reranker_smoke_passed=True,
        qdrant_smoke_passed=True,
        joined_count=518_254,
    )
    with pytest.raises(RuntimeError, match="518255"):
        assert_destructive_preflight(result)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest tests/ingestion/test_hf_pipeline.py -q`

Expected: FAIL because `hf_pipeline` is absent.

- [ ] **Step 3: Implement phase ordering and fail-before-delete gates**

```python
@dataclass(frozen=True)
class PreflightResult:
    snapshot_verified: bool
    content_store_verified: bool
    unit_tests_passed: bool
    embedding_smoke_passed: bool
    reranker_smoke_passed: bool
    qdrant_smoke_passed: bool
    joined_count: int


def assert_destructive_preflight(result: PreflightResult) -> None:
    checks = {
        "snapshot": result.snapshot_verified,
        "content_store": result.content_store_verified,
        "unit_tests": result.unit_tests_passed,
        "embedding": result.embedding_smoke_passed,
        "reranker": result.reranker_smoke_passed,
        "qdrant": result.qdrant_smoke_passed,
        "joined_count_518255": result.joined_count == 518_255,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Destructive preflight failed: {', '.join(failed)}")
```

`smoke` performs:

1. one real two-document embedding request and checks both vectors have 1024 finite values;
2. one real reranker request with three documents and checks index/document plus finite score fields;
3. create/upload/dense-query/sparse-query/hybrid-query/delete on a uniquely named temporary Qdrant collection;
4. write only status, latency, dimensions, and temporary collection name to the report.

No credential or response header is written.

- [ ] **Step 4: Implement streaming preparation and upload with bounded CPU/network work**

The full iterator uses SQLite keyset pagination:

```sql
SELECT document_id
FROM metadata
WHERE document_id > ?
ORDER BY document_id
LIMIT ?
```

For each upload batch:

1. resolve the exact batch from `ContentStore`;
2. create dense and sparse retrieval texts;
3. send dense texts in bounded async HTTP batches;
4. encode sparse texts in a bounded `ProcessPoolExecutor`;
5. build points without full content;
6. call Qdrant bulk upload in `asyncio.to_thread`;
7. mark the checkpoint complete only after upload returns successfully;
8. release documents, texts, vectors, and points before loading the next batch.

On resume, skip completed batch IDs, retain deterministic IDs, and upsert any partially transmitted incomplete batch.

- [ ] **Step 5: Implement measured 1,000/10,000 tuning and report**

Benchmark these concrete candidates:

```python
TUNING_CANDIDATES = (
    {"embed_concurrency": 4, "embed_batch": 16, "upload_batch": 128, "upload_parallel": 2},
    {"embed_concurrency": 8, "embed_batch": 32, "upload_batch": 256, "upload_parallel": 4},
    {"embed_concurrency": 12, "embed_batch": 32, "upload_batch": 256, "upload_parallel": 4},
)
BASELINE = {"embed_concurrency": 1, "embed_batch": 8, "upload_batch": 8, "upload_parallel": 1}
```

Run the 1,000-document benchmark first, reject candidates with permanent failures or unbounded retry growth, then run baseline and the selected candidate on the same deterministic 10,000-document ID range. The optimized path must reach at least 3x baseline unless the report proves embedding-service throttling through 429 counts; in that case choose the fastest zero-failure rate below the observed limit and record the exception.

`ingestion_report.json` includes snapshot revision/hashes, store counts, selected tuning values, baseline/optimized docs per second, wall times, peak in-flight documents, retries by category, failures, Qdrant point count, optimizer status, random hash checks, and command version.

- [ ] **Step 6: Add exact CLI**

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion.hf_pipeline")
    subcommands = parser.add_subparsers(dest="phase", required=True)
    subcommands.add_parser("download")
    subcommands.add_parser("prepare")
    subcommands.add_parser("smoke")
    subcommands.add_parser("benchmark")
    full = subcommands.add_parser("full")
    full.add_argument("--delete-existing", action="store_true")
    full.add_argument("--yes", action="store_true")
    subcommands.add_parser("verify")
    return parser
```

`full --delete-existing --yes` still calls `assert_destructive_preflight`; flags cannot bypass validation or unexpected-collection protection.

- [ ] **Step 7: Run orchestration tests**

Run: `python -m pytest tests/ingestion/test_hf_pipeline.py -q`

Expected: PASS, including a fake-service resume test where batch 1 succeeds, batch 2 fails, and the second run uploads only batch 2 onward.

- [ ] **Step 8: Commit only if explicitly authorized**

```powershell
git add app/ingestion/hf_pipeline.py tests/ingestion/test_hf_pipeline.py
git commit -m "feat: orchestrate resumable full corpus ingestion"
```

---

### Task 8: Replace Runtime Search with One Hybrid Document Query and Dynamic Evidence Reranking

**Files:**
- Create: `app/services/clients.py`
- Create: `app/services/retrieval.py`
- Modify: `app/services/rag_pipeline.py`
- Modify: `app/main.py`
- Replace: `tests/test_rag_pipeline.py`
- Create: `tests/services/test_retrieval.py`
- Create: `tests/services/test_clients.py`

**Interfaces:**
- Produces: `get_http_client`, `get_qdrant_client`, `close_clients`, `LegalRetriever.retrieve(query) -> list[EvidenceChunk]`.
- Consumes: `ContentStore`, `chunk_document`, `SparseEncoder`, BGE-M3 endpoint, BGE reranker endpoint, and named Qdrant vectors.

- [ ] **Step 1: Write failing one-query, local-resolution, lexical-bound, and fail-closed tests**

```python
# tests/services/test_retrieval.py
import pytest

from app.services.retrieval import lexical_prefilter


def test_lexical_prefilter_bounds_remote_rerank_input(evidence_chunks) -> None:
    selected = lexical_prefilter("thuế thu nhập cá nhân", evidence_chunks, limit=3)
    assert len(selected) == 3
    assert "thuế" in selected[0].text.lower()


@pytest.mark.asyncio
async def test_retriever_uses_one_qdrant_hybrid_query(retriever, fake_qdrant) -> None:
    evidence = await retriever.retrieve("điều kiện khấu trừ thuế")
    assert fake_qdrant.query_points.await_count == 1
    call = fake_qdrant.query_points.await_args.kwargs
    assert [prefetch.using for prefetch in call["prefetch"]] == ["dense", "bm25"]
    assert evidence


@pytest.mark.asyncio
async def test_retriever_fails_closed_when_content_hash_is_invalid(broken_store_retriever) -> None:
    assert await broken_store_retriever.retrieve("thuế") == []
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/services/test_retrieval.py tests/services/test_clients.py -q`

Expected: FAIL because runtime client/retrieval modules are absent.

- [ ] **Step 3: Implement application-scoped clients**

```python
# app/services/clients.py
_http_client: httpx.AsyncClient | None = None
_qdrant_client: AsyncQdrantClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )
    return _http_client


def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=30.0,
        )
    return _qdrant_client


async def close_clients() -> None:
    global _http_client, _qdrant_client
    if _http_client is not None:
        await _http_client.aclose()
    if _qdrant_client is not None:
        await _qdrant_client.close()
    _http_client = None
    _qdrant_client = None
```

Initialize lazily and call `close_clients` from FastAPI shutdown. No dense or sparse function may construct and close its own remote client.

- [ ] **Step 4: Implement one Qdrant hybrid query**

```python
response = await qdrant.query_points(
    collection_name=settings.LEGAL_COLLECTION_NAME,
    prefetch=[
        models.Prefetch(
            query=dense_vector,
            using=settings.DENSE_VECTOR_NAME,
            limit=settings.RETRIEVAL_DOCUMENT_LIMIT,
        ),
        models.Prefetch(
            query=sparse_encoder.encode_query(query),
            using=settings.SPARSE_VECTOR_NAME,
            limit=settings.RETRIEVAL_DOCUMENT_LIMIT,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=settings.RETRIEVAL_DOCUMENT_LIMIT,
    with_payload=True,
    with_vectors=False,
)
```

Validate every payload revision equals the configured revision, resolve `content_store_key` values in one local call, verify hashes, dynamically chunk each candidate, and discard unresolved/corrupt candidates. If all evidence disappears, return an empty list.

`lexical_prefilter` tokenizes the query and chunks with the same normalized terms, scores exact phrase match plus `sum(1 + log(term_frequency))`, preserves deterministic tie order by document ID/citation, and returns at most 64 chunks.

- [ ] **Step 5: Implement bounded reranking and grounded context**

Send only the lexical-prefilter output to BGE-reranker-v2-M3. Require a valid result index or exact returned document, finite score, and an in-range mapping. Return the top three `EvidenceChunk` values. On timeout, invalid response, or empty accepted results, return no evidence rather than unreranked fallback documents.

Update `run_advanced_rag` to:

1. rewrite once;
2. retrieve once with the rewritten query;
3. convert evidence to `formatted_context()` strings;
4. call the answer model only when evidence exists;
5. retain the public return type `Tuple[str, List[str], Dict[str, float]]`;
6. report `t_retrieval`, `t_content`, `t_chunk`, `t_rerank`, `t_llm`, and `t_total`.

- [ ] **Step 6: Run runtime tests**

Run:

```powershell
python -m pytest tests/services/test_clients.py tests/services/test_retrieval.py tests/test_rag_pipeline.py -q
python -m compileall -q app
```

Expected: PASS; no real network call occurs in unit tests.

- [ ] **Step 7: Commit only if explicitly authorized**

```powershell
git add app/services/clients.py app/services/retrieval.py app/services/rag_pipeline.py app/main.py tests/services/test_clients.py tests/services/test_retrieval.py tests/test_rag_pipeline.py
git commit -m "feat: add two-stage legal evidence retrieval"
```

---

### Task 9: Make Semantic Cache Revision-Aware and Add Reliability Disclosures

**Files:**
- Modify: `app/services/semantic_cache.py`
- Modify: `app/services/rag_pipeline.py`
- Modify: `app/templates/index.html`
- Create: `tests/services/test_semantic_cache.py`
- Create: `tests/services/test_reliability_disclosure.py`

**Interfaces:**
- Produces: revision-bound semantic-cache keys/filtering and user-visible/source-status warnings.
- Consumes: shared Qdrant/HTTP clients and pinned dataset revision.

- [ ] **Step 1: Write failing revision-aware cache and disclosure tests**

```python
# tests/services/test_semantic_cache.py
from app.services.semantic_cache import semantic_cache_point_id


def test_cache_identity_changes_with_corpus_revision() -> None:
    first = semantic_cache_point_id("thuế thu nhập", "revision-a")
    second = semantic_cache_point_id("thuế thu nhập", "revision-b")
    assert first != second
```

```python
# tests/services/test_reliability_disclosure.py
from pathlib import Path


def test_ui_contains_external_dataset_and_official_source_warning() -> None:
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert "nguồn dữ liệu bên thứ ba" in html.lower()
    assert "nguồn chính thức" in html.lower()
    assert "tư vấn pháp lý" in html.lower()
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/services/test_semantic_cache.py tests/services/test_reliability_disclosure.py -q`

Expected: FAIL because the identity helper and disclosure are absent.

- [ ] **Step 3: Bind cache identity and hits to revision**

```python
def semantic_cache_point_id(user_query: str, revision: str) -> str:
    normalized = " ".join(user_query.casefold().split())
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{revision}\n{normalized}"))
```

Save `corpus_revision` in every cache payload. Query with:

```python
query_filter=models.Filter(
    must=[
        models.FieldCondition(
            key="corpus_revision",
            match=models.MatchValue(value=settings.DATASET_REVISION),
        )
    ]
)
```

Retain the `>= 0.96` threshold and 1024 dimensions. Use shared clients. Do not delete/recreate the cache collection on a request; schema creation belongs in application startup or an explicit administration step.

- [ ] **Step 4: Add answer and UI reliability language**

The answer system prompt must say:

```text
Nguồn dữ liệu là bộ sưu tập nghiên cứu của bên thứ ba, không phải cơ sở dữ liệu
pháp luật chính thức và không tự xác nhận tình trạng hiệu lực. Không được khẳng
định văn bản còn hiệu lực nếu bằng chứng không nêu rõ. Luôn dẫn số văn bản,
Điều/Khoản và URL nguồn khi có; yêu cầu người dùng kiểm tra lại trên nguồn chính
thức hiện hành hoặc với người có chuyên môn. Nội dung chỉ nhằm cung cấp thông tin,
không phải tư vấn pháp lý.
```

Place a concise equivalent warning in the initial page near the chat input so it is visible before a question is submitted.

- [ ] **Step 5: Run cache/disclosure and service tests**

Run:

```powershell
python -m pytest tests/services/test_semantic_cache.py tests/services/test_reliability_disclosure.py tests/services/test_retrieval.py tests/test_rag_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit only if explicitly authorized**

```powershell
git add app/services/semantic_cache.py app/services/rag_pipeline.py app/templates/index.html tests/services/test_semantic_cache.py tests/services/test_reliability_disclosure.py
git commit -m "feat: bind cache and answers to corpus provenance"
```

---

### Task 10: Document Operations, Run All Gates, Download, Reset, Full Index, and Verify

**Files:**
- Modify: `README.md`
- Modify: `instructions.md`
- Create: `docs/huggingface-ingestion-runbook.md`
- Create: `tests/test_documentation.py`
- Generate ignored: `data/huggingface/vohuutridung__vietnamese-legal-documents/4d4e10b201544e8a4c49a1d3fa496595a7d486d0/manifest.json`
- Generate ignored: `data/huggingface/content_store.sqlite3`
- Generate ignored: `data/huggingface/ingestion_state.sqlite3`
- Generate ignored: `data/huggingface/ingestion_report.json`

**Interfaces:**
- Produces: reproducible operator commands, audit artifacts, new remote collection, final verification evidence.
- Consumes: every preceding task.

- [ ] **Step 1: Write failing documentation contract tests**

```python
# tests/test_documentation.py
from pathlib import Path


def test_readme_documents_pinned_full_run_and_disclaimer() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "4d4e10b201544e8a4c49a1d3fa496595a7d486d0" in readme
    assert "python -m app.ingestion.hf_pipeline full --delete-existing --yes" in readme
    assert "518,255" in readme
    assert "không phải" in readme.lower()
    assert "tư vấn pháp lý" in readme.lower()
```

- [ ] **Step 2: Run documentation test and confirm RED**

Run: `python -m pytest tests/test_documentation.py -q`

Expected: FAIL until the operational commands and disclaimer are complete.

- [ ] **Step 3: Write exact runbook and README sections**

Document these commands:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
python -m app.ingestion.hf_pipeline smoke
python -m app.ingestion.hf_pipeline benchmark
python -m app.ingestion.hf_pipeline full --delete-existing --yes
python -m app.ingestion.hf_pipeline verify
```

Explain:

- disk requirements and paths;
- `.part` resume;
- manifest/checksum verification;
- content-store rebuild versus reuse;
- checkpoint resume after process/network interruption;
- why one point per document is necessary under approximately 4 GB;
- why MongoDB is not used for corpus retrieval;
- how benchmarks select concurrency/batch values;
- how to inspect retries/failures/optimizer state;
- how to recover when Qdrant quota is exhausted without losing local preparation;
- exact dataset attribution and CC BY 4.0 publisher declaration;
- dataset source/revision limitations and lack of official/current-effect guarantees;
- official-source/qualified-counsel verification requirement.

- [ ] **Step 4: Run all local non-network gates**

Run:

```powershell
python -m pytest -q
python -m compileall -q app scripts tests
git diff --check
rg -n -i --hidden "crawl|crawler|crawled|scrapling|vbpl|vietlaw|vietlex_laws_crawler_kb|raw_legal_documents|raw_data|postprocessing" . -g '!.git/**' -g '!.venv/**' -g '!.code-review-graph/**' -g '!docs/superpowers/specs/2026-07-29-huggingface-full-corpus-qdrant-design.md' -g '!docs/superpowers/plans/2026-07-29-huggingface-full-corpus-qdrant.md'
```

Expected: tests and compile PASS, diff check is clean, and the crawler residual scan returns no matches.

- [ ] **Step 5: Download and prepare the complete pinned local corpus**

Run:

```powershell
python -m app.ingestion.hf_pipeline download
python -m app.ingestion.hf_pipeline prepare
```

Expected:

- 13 files verified under the pinned snapshot directory;
- remote/local total size and every SHA-256 recorded;
- exactly 518,255 unique metadata IDs;
- exactly 518,255 unique content IDs;
- exactly 518,255 joined documents;
- SQLite integrity check returns `ok`;
- no missing join, duplicate ID, or empty-content blocker;
- report records compression ratio and quality flags.

- [ ] **Step 6: Run real service smoke and measured benchmarks**

Run:

```powershell
python -m app.ingestion.hf_pipeline smoke
python -m app.ingestion.hf_pipeline benchmark
```

Expected:

- embedding vectors are exactly 1024 dimensions;
- reranker contract maps valid documents/scores;
- temporary Qdrant collection passes dense, sparse, and hybrid queries and is deleted;
- 1,000-document tuning completes;
- baseline and optimized 10,000-document measurements complete with zero permanent failures;
- selected settings meet 3x baseline or the report records embedding-service throttling and the fastest stable values.

- [ ] **Step 7: Execute the already authorized destructive reset and full resumable indexing**

Run:

```powershell
python -m app.ingestion.hf_pipeline full --delete-existing --yes
```

Expected ordering:

1. rerun all preflight checks;
2. list collections and abort if any unexpected name exists;
3. delete the observed authorized old collections;
4. create only `vietlex_legal_documents_v1`;
5. upload every document with checkpoint progress;
6. restore HNSW/optimizer settings;
7. wait until optimizer state is green;
8. write final report.

If interrupted, rerun the exact same command. Completed checkpoints are not embedded or uploaded again.

- [ ] **Step 8: Reconcile remote/local state and run legal query smoke tests**

Run:

```powershell
python -m app.ingestion.hf_pipeline verify
python -m pytest -q
git diff --check
```

Verification must assert:

- collection count/list matches the intended post-reset state;
- `vietlex_legal_documents_v1` has exactly 518,255 points;
- dense configuration is 1024/FLOAT16/cosine/on-disk;
- sparse configuration is `bm25`/IDF/on-disk;
- random payload IDs resolve to local documents;
- random local SHA-256 values match Qdrant payloads;
- dense, sparse, and hybrid search return revision-matching payloads;
- at least five representative Vietnamese legal questions produce top-three evidence with document number, URL, and article/clause citation where present;
- no answer claims current legal effect without supporting evidence;
- failures table is empty for the successful final run.

- [ ] **Step 9: Run graph-based final review**

Use code-review-graph in this order:

1. `get_minimal_context_tool` for the migration;
2. `detect_changes_tool` against `HEAD`;
3. `query_graph_tool` with `tests_for` for changed runtime functions;
4. inspect every high-risk changed flow;
5. rerun the specific tests for any reported gap.

Expected: no dangling importer references to removed crawler modules, no uncovered destructive path, and no high-risk issue left unresolved.

- [ ] **Step 10: Commit only after explicit user authorization**

```powershell
git add README.md instructions.md docs/huggingface-ingestion-runbook.md tests/test_documentation.py
git commit -m "docs: document full legal corpus operations"
```

Never add files under `data/huggingface/`.

---

## Plan Self-Review

- Spec coverage: every objective in sections 1–10 maps to Tasks 1–10; crawler deletion is a verified prerequisite rather than repeated here.
- Destructive ordering: Tasks 1–9 and Task 10 Steps 1–6 are non-destructive to existing production collections; deletion appears only after local and real-service gates.
- Capacity: one 1024-dimensional FLOAT16 point per document, on-disk vectors/payload/sparse index, bounded sparse terms, and no full content in Qdrant.
- Reliability: pinned revision, file hashes, ID joins, content hashes, quality flags, citations, cache revision, UI/prompt/README disclaimers, and fail-closed retrieval are covered.
- Throughput: bounded async embedding, process-pool sparse encoding, parallel Qdrant upload, delayed HNSW, checkpoints, and measured tuning are covered.
- Type consistency: `document_id` remains `int`; Qdrant point ID remains deterministic UUIDv5; `content_store_key` remains decimal text; runtime evidence remains `EvidenceChunk` until converted to the existing `List[str]` public contract.
- Placeholder scan: the plan contains no deferred implementation markers; all gates, paths, names, limits, schemas, commands, and required behaviors are explicit.
- Git policy: every commit is conditional on separate explicit authorization.
