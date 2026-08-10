# VietLex Qdrant Structural Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an opt-in, user-operated Qdrant structural-index pilot that streams the 827 primary-legislation documents, uses Qdrant Cloud Inference for Qwen dense and Qdrant BM25 vectors, and produces reproducible quality evidence without changing the Pinecone v1 production path.

**Architecture:** Keep the existing Pinecone/Qdrant-inference v1 path untouched and add isolated structural indexing, transport, retrieval, and evaluation modules. Every remote phase is independently gated by immutable local artifacts, clean source provenance, exact collection/model hashes, and an explicit write authorization; default tests and local planning make zero provider calls. The structural collection stores final chunk IDs, so model-probe rows and resumed uploads are idempotent and no full record list is held in memory.

**Tech Stack:** Python 3.11+, Pydantic v2, `pydantic-settings`, `qdrant-client` 1.18.x, SQLite, pytest, Ruff, existing VietLex content store/evaluation schemas.

## Global Constraints

- Scope is exactly legal types `Hiến pháp`, `Luật`, and `Pháp lệnh` from `vohuutridung/vietnamese-legal-documents@4d4e10b201544e8a4c49a1d3fa496595a7d486d0`.
- Expected local scope is 827 documents and 134,334 structural records at 420 approximate whitespace tokens with overlap 48; live commands fail closed on drift rather than rewriting these values.
- Target collection is exactly `vietlex-legal-rag-v2-pilot`; named vectors are `dense` at 1024/cosine/on-disk and `bm25` with IDF/on-disk sparse indexing.
- Dense candidate is exactly `Qwen/Qwen3-Embedding-0.6B`; sparse model is exactly `qdrant/bm25`; passage text has no query instruction.
- The comparison reference is recomputed on the identical candidate set with Pinecone Inference `llama-text-embed-v2` at 1024 dimensions; it performs inference only and writes no Pinecone record/index.
- Dense query format is exactly `Instruct: {instruction}\nQuery:{normalized_query}` with instruction version `vietlex-vn-legal-retrieval-v1` recorded in every artifact.
- Production contains no local dense or sparse embedding fallback and never silently substitutes a provider model, dimension, model option, or query instruction.
- Pinecone v1, Qdrant staging collections, production factory defaults, credentials, `.env`, and the 518,255-document corpus remain unchanged.
- No command in this plan deletes, recreates, renames, cuts over, or implicitly cleans a remote collection or index.
- `audit`, `plan`, default pytest, and local verification make zero provider calls; all live phases are reported `NOT RUN` unless their commands actually complete.
- Worktrees remain off. Execution is inline unless the user explicitly requests delegated agents.
- Each task follows RED, minimal GREEN, focused verification, CRG diff review, self-review, then one review-clean local commit. Push is not part of this plan.
- Remote gates bind the exact `source_state_sha256`; generated evaluation/index-pilot artifacts may make Git dirty but cannot change that source hash.

## File and interface map

- `app/ingestion/structural_index.py`: canonical local record stream and body-free manifest accumulation.
- `app/ingestion/structural_qdrant.py`: exact collection/model contract, provider error typing, public raw REST transport that retains inference usage.
- `app/ingestion/structural_pilot.py`: immutable audit/plan artifacts, capacity math, authorization, create/finalize/verify orchestration.
- `app/ingestion/structural_checkpoint.py`: SQLite record-level acknowledgement ledger bound to source/plan/collection hashes.
- `app/ingestion/structural_upload.py`: adaptive bounded upload scheduler and retry accounting.
- `app/evaluation/structural_model_probe.py`: real verified-gold subset selection, model contract probe, and candidate-set quality gate.
- `app/services/structural_retrieval.py`: Qdrant dense/BM25/exact lanes, deterministic RRF, bounded reranking, honest stage trace.
- `app/evaluation/structural_pilot_eval.py`: provider-online/offline-metric separation and immutable structural-pilot runs.
- `run_structural_index_pilot.py`: user-operated `audit`, `plan`, `create`, `probe-model`, `upload`, `finalize`, and `verify` phases.
- `run_structural_retrieval_eval.py`: user-operated `benchmark` entrypoint; no generation, guardrails, or Ragas.

---

### Task 1: Nullable provenance and bounded structural streaming

**Files:**
- Modify: `app/ingestion/structural_index.py`
- Modify: `tests/ingestion/test_structural_index.py`

**Interfaces:**
- Consumes: `ContentStore.get_many()`, `chunk_document()`, pinned repository/revision, sorted document IDs.
- Produces: `iter_structural_records(store, document_ids, *, repository, revision, max_tokens=420, overlap_tokens=48) -> Iterator[StructuralRecord]`, `StructuralManifestBuilder.add(record) -> None`, `StructuralManifestBuilder.build() -> StructuralCorpusManifest`, and the compatibility wrappers `build_structural_records()` and `build_structural_manifest()`.

- [ ] **Step 1: Add failing nullable, streaming, and manifest-equivalence tests**

Add these tests and update `_document()` to accept `issuing_authority: str = "Quốc hội"`:

```python
def test_stream_preserves_missing_issuing_authority_as_null() -> None:
    store = FakeStore({72_273: _document(72_273, issuing_authority="")})
    rows = list(iter_structural_records(
        store,
        [72_273],
        repository="owner/legal-corpus",
        revision="revision-1",
    ))
    assert rows
    assert {row.issuing_authority for row in rows} == {None}


def test_stream_reads_bounded_document_batches(monkeypatch) -> None:
    documents = {index: _document(index) for index in range(1, 258)}
    store = FakeStore(documents)
    requested: list[list[int]] = []
    original = store.get_many
    store.get_many = lambda ids: (requested.append(list(ids)) or original(ids))
    assert sum(1 for _ in iter_structural_records(
        store,
        sorted(documents),
        repository="owner/legal-corpus",
        revision="revision-1",
    )) > 257
    assert [len(batch) for batch in requested] == [128, 128, 1]


def test_streaming_manifest_matches_sequence_wrapper() -> None:
    store = FakeStore({1: _document(1), 2: _document(2)})
    rows = build_structural_records(
        store,
        [1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
    )
    builder = StructuralManifestBuilder(
        selected_document_ids=[1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=420,
        overlap_tokens=48,
    )
    for row in rows:
        builder.add(row)
    assert builder.build() == build_structural_manifest(
        rows,
        selected_document_ids=[1, 2],
        repository="owner/legal-corpus",
        revision="revision-1",
        max_tokens=420,
        overlap_tokens=48,
    )
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_index.py -q`

Expected: collection fails because `issuing_authority` is required and the iterator/builder do not exist.

- [ ] **Step 3: Implement the iterator and nullable field**

Use these exact public declarations and keep per-document chunk lists bounded inside the iterator:

```python
from collections.abc import Iterator, Sequence


class StructuralRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    document_id: int = Field(gt=0)
    document_number: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    legal_type: str = Field(min_length=1)
    issuing_authority: str | None
    issuance_date: str | None
    article: str | None
    clause: str | None
    heading_path: str
    citation: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    dataset_revision: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding: None = None


def iter_structural_records(
    store: ContentStore,
    document_ids: Sequence[int],
    *,
    repository: str,
    revision: str,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> Iterator[StructuralRecord]:
    ordered_ids = _validated_document_ids(document_ids)
    repository = _nonblank(repository, "repository")
    revision = _nonblank(revision, "revision")
    _validate_chunk_limits(max_tokens, overlap_tokens)
    seen_record_ids: set[str] = set()
    for offset in range(0, len(ordered_ids), _DOCUMENT_READ_BATCH_SIZE):
        batch_ids = ordered_ids[offset:offset + _DOCUMENT_READ_BATCH_SIZE]
        documents = store.get_many(batch_ids)
        _validate_document_batch(batch_ids, documents)
        for document_id in batch_ids:
            document = documents[document_id]
            _validate_document(document_id, document)
            chunks = chunk_document(
                document.metadata,
                document.content,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
            )
            if not chunks:
                raise StructuralIndexError(
                    f"document {document_id} produced no structural chunks"
                )
            for record in _records_for_document(
                document,
                chunks,
                repository=repository,
                revision=revision,
                max_tokens=max_tokens,
            ):
                if record.record_id in seen_record_ids:
                    raise StructuralIndexError("structural record ID collision")
                seen_record_ids.add(record.record_id)
                yield record


def build_structural_records(store, document_ids, **kwargs) -> list[StructuralRecord]:
    return list(iter_structural_records(store, document_ids, **kwargs))
```

Normalize source provenance with a separate nullable helper; do not weaken other required metadata:

```python
def _nullable_nonblank(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
```

Set `issuing_authority=_nullable_nonblank(metadata.issuing_authority)` in `_records_for_document()`.

- [ ] **Step 4: Implement the streaming manifest accumulator**

The manifest remains body-free and changes to schema `2.0.0`; it counts body bytes/tokens directly from each record and hashes the canonical ordered ID JSON incrementally:

```python
class StructuralCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["2.0.0"] = "2.0.0"
    dataset_repository: str
    dataset_revision: str
    legal_types: tuple[str, ...]
    document_count: int = Field(gt=0)
    record_count: int = Field(gt=0)
    per_legal_type_counts: dict[str, int]
    selected_document_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_record_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    body_bytes: int = Field(gt=0)
    approximate_token_count: int = Field(gt=0)
    chunk_max_tokens: int = Field(gt=0)
    chunk_overlap_tokens: int = Field(ge=0)
    provider_calls: Literal[0] = 0


class StructuralManifestBuilder:
    def __init__(self, *, selected_document_ids, repository, revision,
                 max_tokens=420, overlap_tokens=48) -> None:
        self._ids = _validated_document_ids(selected_document_ids)
        self._repository = _nonblank(repository, "repository")
        self._revision = _nonblank(revision, "revision")
        _validate_chunk_limits(max_tokens, overlap_tokens)
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._seen_records: set[str] = set()
        self._document_types: dict[int, str] = {}
        self._record_hash = hashlib.sha256(b"[")
        self._record_count = 0
        self._body_bytes = 0
        self._tokens = 0

    def add(self, record: StructuralRecord) -> None:
        if record.record_id in self._seen_records:
            raise StructuralIndexError("structural record IDs must be unique")
        if record.document_id not in set(self._ids):
            raise StructuralIndexError("record document IDs do not match the selected document set")
        if record.dataset_revision != self._revision:
            raise StructuralIndexError("record dataset revision mismatch")
        if record.legal_type not in PRIMARY_LEGAL_TYPES:
            raise StructuralIndexError("record legal type is outside structural scope")
        previous = self._document_types.setdefault(record.document_id, record.legal_type)
        if previous != record.legal_type:
            raise StructuralIndexError("document legal type is inconsistent")
        if self._record_count:
            self._record_hash.update(b",")
        self._record_hash.update(json.dumps(record.record_id, ensure_ascii=False).encode("utf-8"))
        self._seen_records.add(record.record_id)
        self._record_count += 1
        self._body_bytes += len(record.body.encode("utf-8"))
        self._tokens += record.token_count

    def build(self) -> StructuralCorpusManifest:
        if not self._record_count:
            raise StructuralIndexError("structural records must not be empty")
        if set(self._document_types) != set(self._ids):
            raise StructuralIndexError("record document IDs do not match the selected document set")
        ordered_hash = self._record_hash.copy()
        ordered_hash.update(b"]")
        return StructuralCorpusManifest(
            dataset_repository=self._repository,
            dataset_revision=self._revision,
            legal_types=PRIMARY_LEGAL_TYPES,
            document_count=len(self._ids),
            record_count=self._record_count,
            per_legal_type_counts=dict(sorted(Counter(self._document_types.values()).items())),
            selected_document_ids_sha256=_canonical_sha256(self._ids),
            ordered_record_ids_sha256=ordered_hash.hexdigest(),
            body_bytes=self._body_bytes,
            approximate_token_count=self._tokens,
            chunk_max_tokens=self._max_tokens,
            chunk_overlap_tokens=self._overlap_tokens,
        )
```

Cache `set(self._ids)` once as `_id_set` in the final implementation. `build_structural_manifest()` creates this builder, calls `add()` for the supplied sequence, and returns `build()`.

- [ ] **Step 5: Run GREEN, lint, review, and commit**

Run:

```powershell
python -m pytest tests/ingestion/test_structural_index.py -q
python -m ruff check app/ingestion/structural_index.py tests/ingestion/test_structural_index.py
git diff --check
```

Use CRG `detect_changes` on the task diff, inspect every reported caller/test, then commit:

```powershell
git add app/ingestion/structural_index.py tests/ingestion/test_structural_index.py
git commit -m "fix(ingestion): stream structural records safely"
```

### Task 2: Exact Qdrant collection, inference, and usage transport contract

**Files:**
- Modify: `app/config.py`
- Create: `app/ingestion/structural_qdrant.py`
- Create: `tests/ingestion/test_structural_qdrant.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`, `StructuralRecord`, `system_ssl_context()`, `qdrant_client.QdrantClient`, and public `client.http.points_api` / `client.http.search_api` methods.
- Produces: `StructuralQdrantContract.from_settings(settings)`, `create_structural_qdrant_client(settings)`, `StructuralQdrantTransport.upsert_with_usage()`, `StructuralQdrantTransport.query_with_usage()`, `point_from_record()`, `dense_query_document()`, and typed `StructuralProviderError` / `InferenceUsageReceipt`.

- [ ] **Step 1: Add failing configuration and exact-wire-contract tests**

```python
def test_structural_contract_defaults_are_opt_in_and_exact() -> None:
    settings = Settings(_env_file=None)
    contract = StructuralQdrantContract.from_settings(settings)
    assert settings.STRUCTURAL_BACKEND_ENABLED is False
    assert contract.collection_name == "vietlex-legal-rag-v2-pilot"
    assert contract.dense_model == "Qwen/Qwen3-Embedding-0.6B"
    assert contract.dense_size == 1024
    assert contract.sparse_model == "qdrant/bm25"
    assert contract.dense_model_options == {}


def test_point_uses_cloud_documents_and_preserves_null(record) -> None:
    point = point_from_record(record, exact_contract())
    assert point.vector["dense"] == models.Document(
        text=record.body,
        model="Qwen/Qwen3-Embedding-0.6B",
        options={},
    )
    assert point.vector["bm25"] == models.Document(
        text=record.body,
        model="qdrant/bm25",
        options={},
    )
    assert point.payload["issuing_authority"] is None
    assert point.payload["chunk_sha256"] == record.chunk_sha256


def test_dense_query_instruction_is_versioned_and_sparse_query_is_raw() -> None:
    contract = exact_contract()
    assert dense_query_document("  Điều 16  ", contract).text == (
        "Instruct: Given a Vietnamese legal question, retrieve relevant "
        "statutory provisions and preserve exact legal references.\n"
        "Query:Điều 16"
    )
    assert sparse_query_document("  Điều 16  ", contract).text == "Điều 16"


def test_raw_transport_preserves_inference_usage(fake_raw_client, record) -> None:
    receipt = StructuralQdrantTransport(fake_raw_client, exact_contract()).upsert_with_usage(
        [point_from_record(record, exact_contract())]
    )
    assert receipt.model_tokens == {
        "Qwen/Qwen3-Embedding-0.6B": 41,
        "qdrant/bm25": 41,
    }
    assert receipt.status == "completed"
```

Also test rejection of a blank instruction, non-1024 size, renamed collection/vector/model, unknown `usage` model, missing inference usage, and response status other than completed/acknowledged.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_qdrant.py tests/test_config.py -q`

Expected: imports and settings fields fail.

- [ ] **Step 3: Add opt-in settings without changing v1 defaults**

Add these exact fields to `Settings` and replace the old Qdrant comment with “Qdrant staging remains the v1 inference path; the structural durable pilot is opt-in.”:

```python
from pydantic import Field

STRUCTURAL_BACKEND_ENABLED: bool = False
STRUCTURAL_COLLECTION_NAME: str = "vietlex-legal-rag-v2-pilot"
STRUCTURAL_DENSE_VECTOR_NAME: str = "dense"
STRUCTURAL_SPARSE_VECTOR_NAME: str = "bm25"
STRUCTURAL_DENSE_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"
STRUCTURAL_DENSE_MODEL_OPTIONS: dict[str, object] = Field(default_factory=dict)
STRUCTURAL_SPARSE_MODEL: str = "qdrant/bm25"
STRUCTURAL_SPARSE_MODEL_OPTIONS: dict[str, object] = Field(default_factory=dict)
STRUCTURAL_VECTOR_SIZE: int = 1024
STRUCTURAL_QUERY_INSTRUCTION_VERSION: str = "vietlex-vn-legal-retrieval-v1"
STRUCTURAL_QUERY_INSTRUCTION: str = (
    "Given a Vietnamese legal question, retrieve relevant statutory "
    "provisions and preserve exact legal references."
)
STRUCTURAL_CHUNK_MAX_TOKENS: int = 420
STRUCTURAL_CHUNK_OVERLAP_TOKENS: int = 48
STRUCTURAL_DENSE_TOP_K: int = 48
STRUCTURAL_BM25_TOP_K: int = 48
STRUCTURAL_FUSED_LIMIT: int = 64
STRUCTURAL_RRF_K: int = 60
STRUCTURAL_PER_DOCUMENT_LIMIT: int = 4
STRUCTURAL_QDRANT_TIMEOUT_SECONDS: float = 120.0
STRUCTURAL_QDRANT_MAX_RETRIES: int = 5
STRUCTURAL_QDRANT_RETRY_BASE_SECONDS: float = 1.0
STRUCTURAL_QDRANT_RETRY_MAX_SECONDS: float = 30.0
STRUCTURAL_UPLOAD_BATCH_MIN: int = 64
STRUCTURAL_UPLOAD_BATCH_MAX: int = 256
STRUCTURAL_UPLOAD_MAX_WORKERS: int = 4
STRUCTURAL_UPLOAD_PREFER_GRPC: bool = True
```

- [ ] **Step 4: Implement the immutable contract and point conversion**

Use a frozen Pydantic model whose `model_validator` enforces every global constant and tuning bound. The payload is exactly:

```python
def point_payload(record: StructuralRecord) -> dict[str, object]:
    return {
        "body": record.body,
        "document_id": record.document_id,
        "document_number": record.document_number,
        "title": record.title,
        "source_url": record.source_url,
        "legal_type": record.legal_type,
        "issuing_authority": record.issuing_authority,
        "issuance_date": record.issuance_date,
        "article": record.article,
        "clause": record.clause,
        "heading_path": record.heading_path,
        "citation": record.citation,
        "token_count": record.token_count,
        "dataset_revision": record.dataset_revision,
        "content_sha256": record.content_sha256,
        "chunk_sha256": record.chunk_sha256,
    }


def point_from_record(record, contract) -> models.PointStruct:
    return models.PointStruct(
        id=record.record_id,
        vector={
            contract.dense_vector_name: models.Document(
                text=record.body,
                model=contract.dense_model,
                options=contract.dense_model_options,
            ),
            contract.sparse_vector_name: models.Document(
                text=record.body,
                model=contract.sparse_model,
                options=contract.sparse_model_options,
            ),
        },
        payload=point_payload(record),
    )


def dense_query_document(query: str, contract) -> models.Document:
    normalized = " ".join(query.split())
    if not normalized:
        raise StructuralQdrantError("query must be nonblank")
    text = f"Instruct: {contract.query_instruction}\nQuery:{normalized}"
    return models.Document(
        text=text,
        model=contract.dense_model,
        options=contract.dense_model_options,
    )
```

- [ ] **Step 5: Implement usage-preserving public REST calls**

Do not call private SDK attributes. `QdrantClient.http` is a documented raw REST client and retains top-level inference usage that the convenience methods discard:

```python
class InferenceUsageReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["acknowledged", "completed"]
    elapsed_seconds: float | None
    model_tokens: dict[str, int]
    attempts: int = Field(default=1, gt=0)


class StructuralProviderError(RuntimeError):
    def __init__(self, *, stage: str, category: str, message: str,
                 transient: bool, attempts: int = 1) -> None:
        super().__init__(message)
        self.stage = stage
        self.category = category
        self.transient = transient
        self.attempts = attempts


class StructuralQdrantTransport:
    def __init__(self, client: QdrantClient, contract: StructuralQdrantContract) -> None:
        self.client = client
        self.contract = contract

    def upsert_with_usage(self, points: Sequence[models.PointStruct]) -> InferenceUsageReceipt:
        response = self.client.http.points_api.upsert_points(
            collection_name=self.contract.collection_name,
            wait=True,
            timeout=int(self.contract.timeout_seconds),
            point_insert_operations=models.PointsList(points=list(points)),
        )
        return _validated_usage_receipt(response, self.contract, stage="upsert")

    def query_with_usage(self, *, document: models.Document, using: str,
                         limit: int, query_filter: models.Filter | None = None,
                         with_vectors: bool = False) -> tuple[list[models.ScoredPoint], InferenceUsageReceipt]:
        response = self.client.http.search_api.query_points(
            collection_name=self.contract.collection_name,
            timeout=int(self.contract.timeout_seconds),
            query_request=models.QueryRequest(
                query=document,
                using=using,
                filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vector=with_vectors,
            ),
        )
        receipt = _validated_usage_receipt(response, self.contract, stage=f"query:{using}")
        if response.result is None:
            raise StructuralProviderError(
                stage=f"query:{using}", category="invalid_response",
                message="Qdrant query result is missing", transient=False,
            )
        return response.result.points, receipt
```

`_validated_usage_receipt()` requires `usage.inference.models`, nonnegative token counts, and only the model expected for that operation. For upserts it requires both dense and BM25 models. It maps transport/HTTP errors to typed transient categories without exposing API keys.

Create the client with `cloud_inference=True`, the configured timeout, `prefer_grpc` only for ordinary database operations, API key, and the existing verified Windows trust context. The usage-preserving inference methods remain REST until an equivalent usage-preserving gRPC wrapper has focused tests.

```python
def create_structural_qdrant_client(settings: Settings) -> QdrantClient:
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        cloud_inference=True,
        prefer_grpc=settings.STRUCTURAL_UPLOAD_PREFER_GRPC,
        timeout=settings.STRUCTURAL_QDRANT_TIMEOUT_SECONDS,
        verify=system_ssl_context(),
        check_compatibility=False,
    )
```

- [ ] **Step 6: Run GREEN, review, and commit**

Run:

```powershell
python -m pytest tests/ingestion/test_structural_qdrant.py tests/test_config.py tests/ingestion/test_qdrant_inference.py -q
python -m ruff check app/config.py app/ingestion/structural_qdrant.py tests/ingestion/test_structural_qdrant.py tests/test_config.py
git diff --check
```

CRG-review config importers and Qdrant client callers, then commit:

```powershell
git add app/config.py app/ingestion/structural_qdrant.py tests/ingestion/test_structural_qdrant.py tests/test_config.py
git commit -m "feat(ingestion): define Qdrant structural contract"
```

### Task 3: Provider-free audit, capacity plan, and immutable authorization

**Files:**
- Create: `app/ingestion/structural_pilot.py`
- Create: `run_structural_index_pilot.py`
- Modify: `app/evaluation/provenance.py`
- Create: `tests/ingestion/test_structural_pilot.py`
- Modify: `tests/evaluation/test_provenance.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`

**Interfaces:**
- Consumes: Tasks 1-2, `ContentStore`, `collect_git_provenance()`, `write_immutable_json()`, and canonical JSON SHA-256.
- Produces: `StructuralCapacityEstimate`, `StructuralPilotPlan`, `RemoteWriteAuthorization`, `audit_structural_corpus()`, `build_structural_pilot_plan()`, `load_bound_plan()`, and provider-free CLI phases `audit` / `plan`.

- [ ] **Step 1: Add failing zero-provider, capacity, artifact, and authorization tests**

```python
def test_plan_streams_exact_scope_without_constructing_client(fake_store, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(structural_pilot, "create_structural_qdrant_client",
                        lambda settings: pytest.fail("provider client constructed"))
    plan = build_structural_pilot_plan(
        store=fake_store,
        settings=exact_settings(),
        output_root=tmp_path,
        capacity=CapacityEnvelope(
            disk_bytes=4 * 1024**3,
            ram_bytes=1024**3,
            vcpu=0.5,
            existing_disk_bytes=0,
            shard_count=1,
        ),
    )
    assert plan.manifest.provider_calls == 0
    assert plan.capacity.safety_headroom_ratio == 0.25
    assert plan.capacity.projected_total_bytes <= plan.capacity.available_disk_bytes
    assert '"body":' not in (tmp_path / plan.run_id / "plan.json").read_text("utf-8")


def test_capacity_includes_every_declared_component() -> None:
    estimate = estimate_capacity(manifest_fixture(), metadata_json_bytes=1000,
                                 disk_bytes=10_000, existing_disk_bytes=100)
    assert set(estimate.components) == {
        "dense_float32", "body_utf8", "metadata_json", "sparse_budget",
        "hnsw_edges", "wal_segments", "safety_headroom",
    }


def test_authorization_rejects_mismatched_source(plan, clean_provenance) -> None:
    with pytest.raises(StructuralPilotError, match="source state"):
        validate_remote_write_authorization(
            plan,
            RemoteWriteAuthorization(
                allow_remote_write=True,
                collection_name="vietlex-legal-rag-v2-pilot",
                plan_sha256=plan.plan_sha256,
                source_state_sha256="0" * 64,
            ),
            clean_provenance,
        )
```

Also assert collision-safe run directories, exact dataset/source hashes, sorted case-independent scope, `BLOCKED_CAPACITY`, rejection of source-state drift, acceptance of artifact-only dirtiness with exact source hash, wrong plan hash, wrong collection, false write flag, and any target containing v1/staging names.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_pilot.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 3: Implement honest capacity math**

Use explicit recorded estimates; do not describe sparse/index overhead as measured bytes:

```python
def estimate_capacity(manifest, *, metadata_json_bytes, disk_bytes,
                      existing_disk_bytes, hnsw_m=16) -> StructuralCapacityEstimate:
    dense = manifest.record_count * 1024 * 4
    body = manifest.body_bytes
    metadata = metadata_json_bytes
    sparse_budget = body * 2
    hnsw_edges = manifest.record_count * hnsw_m * 2 * 4
    base = dense + body + metadata + sparse_budget + hnsw_edges
    wal_segments = math.ceil(base * 0.20)
    before_safety = base + wal_segments
    safety = math.ceil(before_safety * 0.25)
    projected = before_safety + safety
    available = disk_bytes - existing_disk_bytes
    return StructuralCapacityEstimate(
        estimation_method="explicit_conservative_v1",
        components={
            "dense_float32": dense,
            "body_utf8": body,
            "metadata_json": metadata,
            "sparse_budget": sparse_budget,
            "hnsw_edges": hnsw_edges,
            "wal_segments": wal_segments,
            "safety_headroom": safety,
        },
        safety_headroom_ratio=0.25,
        projected_total_bytes=projected,
        cluster_disk_bytes=disk_bytes,
        existing_disk_bytes=existing_disk_bytes,
        available_disk_bytes=available,
        status="PASS_CAPACITY" if projected <= available else "BLOCKED_CAPACITY",
    )
```

Compute `metadata_json_bytes` while streaming by serializing `point_payload(record)` without `body` using sorted compact JSON. Record RAM, vCPU, shard count, every multiplier, and the fact that sparse/HNSW/WAL figures are conservative estimates pending post-finalize measurement.

- [ ] **Step 4: Implement immutable plan models and source binding**

```python
class CapacityEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disk_bytes: int | None = Field(default=None, gt=0)
    ram_bytes: int | None = Field(default=None, gt=0)
    vcpu: float | None = Field(default=None, gt=0)
    existing_disk_bytes: int | None = Field(default=None, ge=0)
    shard_count: int | None = Field(default=None, gt=0)


class RemoteWriteAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allow_remote_write: Literal[True]
    collection_name: Literal["vietlex-legal-rag-v2-pilot"]
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def validate_remote_write_authorization(plan, authorization, provenance) -> None:
    if provenance.status != "ok" or provenance.source_state_sha256 is None:
        raise StructuralPilotError("remote writes require available Git source provenance")
    if provenance.source_state_sha256 != authorization.source_state_sha256:
        raise StructuralPilotError("source state authorization mismatch")
    if plan.plan_sha256 != authorization.plan_sha256:
        raise StructuralPilotError("plan authorization mismatch")
    if plan.contract.collection_name != authorization.collection_name:
        raise StructuralPilotError("collection authorization mismatch")
    if plan.capacity.status != "PASS_CAPACITY":
        raise StructuralPilotError("BLOCKED_CAPACITY")
```

When any capacity-envelope field is absent, the plan still writes an honest `BLOCKED_CAPACITY` artifact with `missing_capacity_inputs`; it never substitutes zero or a generic free-tier description. Add `docs/evaluation/index-pilots/` to `SOURCE_EXCLUDED_PREFIXES` and to the source-diff path exclusions in `collect_git_provenance()`, with a regression proving generated pilot artifacts change `git_dirty` but not `source_state_sha256`.

The immutable run directory is `docs/evaluation/index-pilots/<UTC-run-id>/` and contains `plan.json`, `manifest.json`, `scope.json`, and `report.md`. `plan_sha256` hashes canonical plan content with the hash field excluded. `scope.json` contains IDs/hashes/counts only, never legal bodies or secrets.

- [ ] **Step 5: Add provider-free `audit` and `plan` CLI commands**

Use subparsers and explicit capacity inputs:

```python
plan_parser.add_argument("--disk-bytes", type=positive_int)
plan_parser.add_argument("--ram-bytes", type=positive_int)
plan_parser.add_argument("--vcpu", type=positive_float)
plan_parser.add_argument("--existing-disk-bytes", type=nonnegative_int)
plan_parser.add_argument("--shards", type=positive_int)
plan_parser.add_argument(
    "--output-root",
    type=Path,
    default=Path("docs/evaluation/index-pilots"),
)
```

`audit` prints and writes the exact structural manifest. `plan` additionally binds capacity and command fingerprints. Both return exit 2 on corpus/contract drift and exit 3 on `BLOCKED_CAPACITY`, including missing capacity evidence; neither imports credentials into artifacts or constructs a Qdrant client.

- [ ] **Step 6: Run GREEN, help checks, review, and commit**

```powershell
python -m pytest tests/ingestion/test_structural_pilot.py tests/evaluation/test_provenance.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_index_pilot.py --help
python run_structural_index_pilot.py audit --help
python run_structural_index_pilot.py plan --help
python -m ruff check app/ingestion/structural_pilot.py app/evaluation/provenance.py run_structural_index_pilot.py tests/ingestion/test_structural_pilot.py tests/evaluation/test_provenance.py
git diff --check
git add app/ingestion/structural_pilot.py app/evaluation/provenance.py run_structural_index_pilot.py tests/ingestion/test_structural_pilot.py tests/evaluation/test_provenance.py tests/evaluation/test_default_entrypoints.py
git commit -m "feat(ingestion): plan Qdrant structural pilot"
```

### Task 4: Fail-closed collection creation

**Files:**
- Modify: `app/ingestion/structural_pilot.py`
- Modify: `run_structural_index_pilot.py`
- Modify: `tests/ingestion/test_structural_pilot.py`

**Interfaces:**
- Consumes: Task 3 bound plan/authorization and Task 2 Qdrant client/contract.
- Produces: `create_structural_collection(client, plan, authorization, provenance) -> CollectionCreationReceipt` and CLI phase `create`.

- [ ] **Step 1: Add failing schema and no-recreate tests**

```python
def test_create_uses_exact_empty_collection_schema(bound_plan, authorization, clean_provenance) -> None:
    client = RecordingQdrantClient(exists=False)
    receipt = create_structural_collection(client, bound_plan, authorization, clean_provenance)
    call = client.create_calls[0]
    assert call["collection_name"] == "vietlex-legal-rag-v2-pilot"
    assert call["vectors_config"]["dense"] == models.VectorParams(
        size=1024,
        distance=models.Distance.COSINE,
        on_disk=True,
    )
    assert call["sparse_vectors_config"]["bm25"].modifier == models.Modifier.IDF
    assert call["hnsw_config"].m == 0
    assert call["shard_number"] == 1
    assert receipt.points_count == 0
    assert set(receipt.payload_indexes) == {
        "dataset_revision", "legal_type", "document_id"
    }


def test_create_never_recreates_existing_target(bound_plan, authorization, clean_provenance) -> None:
    client = RecordingQdrantClient(exists=True)
    with pytest.raises(StructuralPilotError, match="already exists"):
        create_structural_collection(client, bound_plan, authorization, clean_provenance)
    assert client.create_calls == []
    assert client.delete_calls == []
```

Also test unreachable endpoint, changed source, capacity failure, schema readback mismatch, nonzero points after create, payload-index failure, and that no delete/recreate method is called on any exception.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_pilot.py -q`

- [ ] **Step 3: Implement exact creation and readback**

```python
created = client.create_collection(
    collection_name=contract.collection_name,
    vectors_config={
        contract.dense_vector_name: models.VectorParams(
            size=contract.dense_size,
            distance=models.Distance.COSINE,
            on_disk=True,
        )
    },
    sparse_vectors_config={
        contract.sparse_vector_name: models.SparseVectorParams(
            index=models.SparseIndexParams(on_disk=True),
            modifier=models.Modifier.IDF,
        )
    },
    shard_number=plan.capacity_envelope.shard_count,
    on_disk_payload=True,
    hnsw_config=models.HnswConfigDiff(m=0, on_disk=True),
    timeout=int(contract.timeout_seconds),
)
if created is not True:
    raise StructuralPilotError("Qdrant did not acknowledge collection creation")
for field, schema in (
    ("dataset_revision", models.PayloadSchemaType.KEYWORD),
    ("legal_type", models.PayloadSchemaType.KEYWORD),
    ("document_id", models.PayloadSchemaType.INTEGER),
):
    client.create_payload_index(
        collection_name=contract.collection_name,
        field_name=field,
        field_schema=schema,
        wait=True,
    )
```

Immediately call `get_collection()` and validate exact vector names, 1024/cosine/on-disk, sparse IDF/on-disk, shard count, HNSW `m=0`, all three payload indexes, and `points_count == 0`. Persist `create-receipt.json` beside the plan using immutable writing; include operation timestamps, readback schema, zero-point count, source/plan hashes, and provider calls, but no credentials.

- [ ] **Step 4: Add exact CLI authorization flags**

```python
create_parser.add_argument("--plan", type=Path, required=True)
create_parser.add_argument("--plan-sha256", required=True)
create_parser.add_argument("--source-state-sha256", required=True)
create_parser.add_argument(
    "--collection",
    choices=["vietlex-legal-rag-v2-pilot"],
    required=True,
)
create_parser.add_argument("--allow-remote-write", action="store_true", required=True)
```

The command exits before constructing the client if artifact, source, collection, capacity, or flag validation fails.

- [ ] **Step 5: Run GREEN, review, and commit**

```powershell
python -m pytest tests/ingestion/test_structural_pilot.py tests/ingestion/test_structural_qdrant.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_index_pilot.py create --help
python -m ruff check app/ingestion/structural_pilot.py run_structural_index_pilot.py tests/ingestion/test_structural_pilot.py
git diff --check
git add app/ingestion/structural_pilot.py run_structural_index_pilot.py tests/ingestion/test_structural_pilot.py
git commit -m "feat(ingestion): gate Qdrant pilot creation"
```

### Task 5: Real verified-gold model probe before bulk upload

**Files:**
- Create: `app/evaluation/structural_model_probe.py`
- Create: `tests/evaluation/test_structural_model_probe.py`
- Modify: `run_structural_index_pilot.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`

**Interfaces:**
- Consumes: verified dataset/sidecar loaders, `select_evaluation_cases(cases, "all-required-verified")`, `matches_required_level()`, Task 1 record stream, Task 2 usage transport, Pinecone hosted inference as the comparison boundary, Task 3 plan, and Task 4 creation receipt.
- Produces: `select_model_probe_records()`, `run_structural_model_probe() -> StructuralModelProbeReport`, acceptance `PASS_MODEL_PROBE | FAIL_QUALITY | BLOCKED_TECHNICAL | BLOCKED_SCOPE`, and CLI phase `probe-model`.

- [ ] **Step 1: Add failing real-scope and denominator tests**

```python
def test_probe_selection_uses_only_verified_required_in_scope_records(cases, records) -> None:
    selection = select_model_probe_records(cases, iter(records))
    assert selection.case_ids == ["case-001", "case-002"]
    assert selection.record_ids == sorted({records[0].record_id, records[2].record_id})
    assert selection.synthetic_records == 0
    assert selection.skipped_cases == {"case-003": "outside_primary_legislation_scope"}


def test_probe_pass_requires_same_denominator_reference_and_provider_usage(fake_transport, fake_reference, probe_input) -> None:
    report = run_structural_model_probe(fake_transport, fake_reference, probe_input)
    assert report.acceptance == "PASS_MODEL_PROBE"
    assert report.metrics["recall_at_1"].numerator == 39
    assert report.metrics["recall_at_1"].denominator == 40
    assert report.metrics["recall_at_3"].value == 1.0
    assert report.metrics["mrr"].value >= 0.9833
    assert report.reference_metrics["case_ids_sha256"] == report.case_ids_sha256
    assert report.metrics["recall_at_1"].value >= report.reference_metrics["recall_at_1"].value
    assert report.provider_usage["Qwen/Qwen3-Embedding-0.6B"] > 0
    assert report.provider_usage["llama-text-embed-v2"] > 0
```

Add tests for exact dataset/sidecar SHA-256, unresolved evidence, candidate/reference case-hash mismatch, missing usage, vector length not 1024, NaN/Inf values, wrong model usage, partial provider failure, idempotent same-ID upsert, 64-row probe batching, no Pinecone storage call, no automatic cleanup, and immutable failure artifact.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_structural_model_probe.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 3: Stream and resolve the real gold subset**

Load the 420-case dataset and v2 sidecar, verify exact case-ID equality, build cases, then select `all-required-verified`. Keep only positive integer document IDs in the structural scope. Stream all structural records once, retaining a record only when this existing matcher says it supports a required label:

```python
candidate = CandidateChunk(
    document_id=record.document_id,
    document_number=record.document_number,
    title=record.title,
    source_url=record.source_url,
    citation=record.citation,
    article=record.article,
    clause=record.clause,
    text=record.body,
    token_count=record.token_count,
)
if any(matches_required_level(label, candidate) for label in required_labels):
    selected_records[record.record_id] = record
```

Every required evidence item must resolve to at least one structural record or its case receives `outside_primary_legislation_scope` / `verified_structure_not_resolved`. If no valid cases remain, return `BLOCKED_SCOPE`; never manufacture a record from reference text.

- [ ] **Step 4: Upsert probe rows and verify exact model output**

Use final deterministic IDs and `upsert_with_usage()` in sorted batches of at most 64. Retrieve every probe row with `with_vectors=["dense", "bm25"]`; assert dense length 1024, all values finite, sparse indices/values nonempty, payload hash equality, and exact collection schema. Sum provider usage from the raw upsert receipts.

For each included case, call `query_with_usage()` with `dense_query_document()`, `using="dense"`, and `limit=3`. A hit is relevant when its payload converted to `CandidateChunk` matches any required verified evidence for that case. Metrics are comparable with the prior 40-question/53-passage candidate smoke:

```python
first_relevant_rank = next(
    (rank for rank, hit in enumerate(hits, 1) if is_relevant(case, hit)),
    None,
)
recall_at_1_numerator += int(first_relevant_rank == 1)
recall_at_3_numerator += int(first_relevant_rank is not None and first_relevant_rank <= 3)
mrr_numerator += 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
```

- [ ] **Step 5: Recompute the Pinecone reference on identical questions/passages**

Create `PineconeReferenceEmbedder` in the same module. It calls only `pinecone.inference.embed()` with model `llama-text-embed-v2`, `dimension=1024`, `input_type="passage"` for the exact selected record bodies and `input_type="query"` for the exact included questions, in bounded 96-input batches. It computes cosine ranks over that same in-memory candidate set and records model, dimension, input counts, token/usage fields exposed by the SDK, case-ID SHA, record-ID SHA, and metrics. It never creates an index or upserts a record. A previously immutable reference probe may be reused only when dataset, sidecar, case-ID, record-ID, text-hash, model, dimension, and source hashes all match.

Set `PASS_MODEL_PROBE` only when candidate and reference case/record hashes are identical, Recall@1 >= max(0.975, reference Recall@1), Recall@3 == 1.0 and is not below reference Recall@3, MRR >= max(0.9833, reference MRR), all contract checks pass, and technical errors are zero. This replaces comparison to an unverified remembered denominator.

- [ ] **Step 6: Add gated `probe-model` CLI and immutable report**

Require the Task 4 creation receipt and the same authorization flags plus either Pinecone inference credentials or a hash-matching immutable reference-probe path. Persist `model-probe.json` with dataset/sidecar/source/plan/create hashes, included/skipped case IDs/reasons, record IDs/hashes, candidate and reference per-query ranks, numerator/denominator/coverage, provider usage, model options, vector validation, latency, and acceptance. On failure leave the small collection unchanged.

- [ ] **Step 7: Run GREEN, review, and commit**

```powershell
python -m pytest tests/evaluation/test_structural_model_probe.py tests/evaluation/test_gold_adjudication.py tests/evaluation/test_retrieval_metrics_v3.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_index_pilot.py probe-model --help
python -m ruff check app/evaluation/structural_model_probe.py tests/evaluation/test_structural_model_probe.py run_structural_index_pilot.py
git diff --check
git add app/evaluation/structural_model_probe.py tests/evaluation/test_structural_model_probe.py run_structural_index_pilot.py tests/evaluation/test_default_entrypoints.py
git commit -m "feat(eval): gate structural model probe"
```

### Task 6: Adaptive resumable upload, finalize, and verification

**Files:**
- Create: `app/ingestion/structural_checkpoint.py`
- Create: `app/ingestion/structural_upload.py`
- Create: `tests/ingestion/test_structural_checkpoint.py`
- Create: `tests/ingestion/test_structural_upload.py`
- Modify: `app/ingestion/structural_pilot.py`
- Modify: `run_structural_index_pilot.py`
- Modify: `tests/ingestion/test_structural_pilot.py`

**Interfaces:**
- Consumes: `PASS_MODEL_PROBE`, source/plan/create/probe hashes, Task 1 stream, Task 2 point/transport, and existing exact collection.
- Produces: `StructuralCheckpointStore`, `AdaptiveUploadController`, `upload_structural_records()`, `finalize_structural_collection()`, `verify_structural_collection()`, and CLI phases `upload`, `finalize`, `verify`.

- [ ] **Step 1: Add failing checkpoint identity and atomicity tests**

```python
def test_checkpoint_resume_is_record_id_based_not_batch_based(tmp_path) -> None:
    store = StructuralCheckpointStore(tmp_path / "structural.sqlite3", binding_fixture())
    store.commit_receipt(batch_receipt([record("a"), record("b")]))
    reopened = StructuralCheckpointStore(tmp_path / "structural.sqlite3", binding_fixture())
    assert reopened.committed_record_hashes() == {"a": sha("a"), "b": sha("b")}
    assert reopened.pending([record("b"), record("c")]) == [record("c")]


def test_checkpoint_rejects_source_plan_model_or_collection_drift(tmp_path) -> None:
    StructuralCheckpointStore(tmp_path / "structural.sqlite3", binding_fixture())
    with pytest.raises(StructuralCheckpointError, match="binding mismatch"):
        StructuralCheckpointStore(tmp_path / "structural.sqlite3",
                                  binding_fixture(plan_sha256="0" * 64))


def test_failed_batch_is_not_checkpointed(tmp_path) -> None:
    checkpoint = StructuralCheckpointStore(tmp_path / "state.sqlite3", binding_fixture())
    with pytest.raises(StructuralProviderError):
        upload_structural_records(failing_transport(), [record("a")], checkpoint,
                                  controller_fixture())
    assert checkpoint.committed_record_hashes() == {}


def test_probe_receipt_seeds_only_exact_acknowledged_ids(tmp_path) -> None:
    checkpoint = StructuralCheckpointStore(tmp_path / "state.sqlite3", binding_fixture())
    checkpoint.import_probe_receipt(probe_report(records=[record("gold")]))
    assert checkpoint.committed_record_hashes() == {"gold": sha("gold")}
```

The SQLite schema has a single `binding` row and `committed_records(record_id PRIMARY KEY, chunk_sha256, batch_sha256, committed_at_utc, dense_tokens, sparse_tokens)`. Use `BEGIN IMMEDIATE`, insert all rows for one acknowledged batch, then commit; roll back on every error. Before streaming, import the immutable probe receipt as an acknowledged batch only after its source/plan/collection/model/record hashes match, so genuine probe rows are not embedded twice.

- [ ] **Step 2: Add failing adaptive-speed and retry tests**

```python
def test_controller_increases_only_after_three_healthy_waves() -> None:
    controller = AdaptiveUploadController(batch_size=64, workers=1, min_batch=64,
                                          max_batch=256, max_workers=4, shard_count=2)
    for _ in range(3):
        controller.observe(UploadWaveResult(success=True, transient_errors=0,
                                            p95_seconds=4.0, rate_limited=False))
    assert controller.batch_size == 128
    assert controller.workers == 2


def test_controller_halves_pressure_after_repeated_transient_errors() -> None:
    controller = AdaptiveUploadController(batch_size=256, workers=4, min_batch=64,
                                          max_batch=256, max_workers=4, shard_count=4)
    controller.observe(UploadWaveResult(success=False, transient_errors=2,
                                        p95_seconds=120.0, rate_limited=True))
    assert controller.batch_size == 128
    assert controller.workers == 2
```

Also test 64-256 bounds, initial workers `min(shards, max_workers)`, bounded exponential delays `1, 2, 4, 8, 16, 30`, permanent errors are attempted once, no duplicate checkpoint rows, probe IDs are skipped only when hashes match, and usage/timing totals are exact.

- [ ] **Step 3: Add a usage-preserving gRPC upload transport**

Use the SDK's public generated gRPC stub and conversion module so upload can take the fast path without losing top-level inference usage:

```python
from qdrant_client import grpc
from qdrant_client.conversions.conversion import RestToGrpc


def upsert_with_usage_grpc(client, contract, points):
    response = client.grpc_points.Upsert(
        grpc.UpsertPoints(
            collection_name=contract.collection_name,
            wait=True,
            points=[RestToGrpc.convert_point_struct(point) for point in points],
            timeout=int(contract.timeout_seconds),
        ),
        timeout=contract.timeout_seconds,
    )
    return _validated_grpc_usage_receipt(response, contract, stage="upsert")
```

At upload preflight, perform one idempotent probe-ID upsert through gRPC. If and only if the failure is typed as endpoint/protocol incompatibility, switch the entire run to the already-tested REST transport and record `transport="rest"` plus the exact fallback reason. Rate limits, timeouts, inference failures, invalid usage, and schema errors do not trigger a transport switch. Never alternate transports per worker.

- [ ] **Step 4: Implement adaptive streaming upload**

`upload_structural_records()` filters committed IDs while iterating, fills only the current bounded wave, and submits at most `workers` batches concurrently. For each batch:

```python
def upload_one_batch(transport, records, contract) -> BatchReceipt:
    points = [point_from_record(record, contract) for record in records]
    receipt = retry_transient(
        lambda: transport.upsert_with_usage(points),
        max_attempts=contract.max_retries,
        base_seconds=contract.retry_base_seconds,
        max_seconds=contract.retry_max_seconds,
    )
    batch_sha256 = canonical_sha256([
        {"record_id": row.record_id, "chunk_sha256": row.chunk_sha256}
        for row in records
    ])
    return BatchReceipt(
        batch_sha256=batch_sha256,
        records=[AcknowledgedRecord(
            record_id=row.record_id,
            chunk_sha256=row.chunk_sha256,
        ) for row in records],
        usage=receipt.model_tokens,
        attempts=receipt.attempts,
        elapsed_seconds=receipt.elapsed_seconds,
    )
```

Checkpoint only after the receipt passes exact model-usage validation. Report records/sec, approximate tokens/sec, dense/sparse provider tokens, p50/p95 latency, retries by category, adaptive changes, remaining count, and source/plan hashes.

- [ ] **Step 5: Implement explicit finalize**

Require exact remote authorization, `PASS_MODEL_PROBE`, upload `committed_count == manifest.record_count`, and count readback equality. Then:

```python
updated = client.update_collection(
    collection_name=contract.collection_name,
    hnsw_config=models.HnswConfigDiff(m=16, on_disk=True),
    timeout=int(contract.timeout_seconds),
)
if updated is not True:
    raise StructuralPilotError("Qdrant did not acknowledge HNSW finalize")
```

Poll `get_collection()` with bounded intervals until collection status is green, optimizer status is ok, indexed vector count reaches the declared dense-vector count when Qdrant exposes it, and HNSW readback is `m=16`. Timeout writes `BLOCKED_TECHNICAL`; it does not revert, delete, or recreate.

- [ ] **Step 6: Implement exact verification**

`verify_structural_collection()` checks collection schema, points count 134,334, source revision, create/probe/upload/finalize hash chain, provider usage, and a deterministic sample. Sample IDs are the first, last, and indices derived from `sha256(plan_sha256 + str(i)) % record_count`; retrieve them with payload/vectors, compare every payload field and hash, dense length/finite values, and nonempty sparse values. Persist a new immutable `verify.json` with `PASS_VERIFY | BLOCKED_TECHNICAL`; never modify the plan.

- [ ] **Step 7: Add guarded CLI phases**

All three phases require `--plan`, the exact upstream receipt path/hash, `--checkpoint` for upload, collection/source/plan authorization fields, and `--allow-remote-write`. `verify` is read-only remotely but still requires exact artifact binding so it cannot certify another collection accidentally.

- [ ] **Step 8: Run GREEN, review, and commit**

```powershell
python -m pytest tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py tests/ingestion/test_structural_qdrant.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_index_pilot.py upload --help
python run_structural_index_pilot.py finalize --help
python run_structural_index_pilot.py verify --help
python -m ruff check app/ingestion/structural_checkpoint.py app/ingestion/structural_upload.py app/ingestion/structural_pilot.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py
git diff --check
git add app/ingestion/structural_checkpoint.py app/ingestion/structural_upload.py app/ingestion/structural_pilot.py run_structural_index_pilot.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py
git commit -m "feat(ingestion): stream resumable Qdrant pilot"
```

### Task 7: Opt-in structural dense/BM25/exact retrieval

**Files:**
- Create: `app/services/structural_retrieval.py`
- Create: `tests/services/test_structural_retrieval.py`

**Interfaces:**
- Consumes: Task 2 query documents/contract/client, existing `LegalFTSIndex`, existing `RemoteReranker`, structural point payloads.
- Produces: `StructuralSourceHit`, `StructuralCandidate`, `StructuralRetrievalTrace`, `StructuralRetrievalOutcome`, `reciprocal_rank_fusion()`, async `StructuralRetriever.retrieve()`, and `build_structural_retriever()`; it does not modify `get_legal_retriever()`.

- [ ] **Step 1: Add failing deterministic fusion and source-error tests**

```python
def test_rrf_retains_source_ranks_scores_and_stable_ties() -> None:
    rows = reciprocal_rank_fusion(
        dense=[hit("a", 0.9), hit("b", 0.8)],
        bm25=[hit("b", 7.0), hit("c", 6.0)],
        exact=[hit("c", 1.0)],
        rrf_k=60,
    )
    assert [row.record_id for row in rows] == ["c", "b", "a"]
    assert rows[1].dense_rank == 2
    assert rows[1].bm25_rank == 1
    assert rows[1].dense_score == 0.8
    assert rows[1].bm25_score == 7.0


@pytest.mark.asyncio
async def test_dense_failure_is_not_converted_to_empty_success() -> None:
    outcome = await retriever(dense_error=TimeoutError("dense timeout")).retrieve("Điều 16")
    assert outcome.status == "partial_technical_error"
    assert outcome.technical_errors["dense"].category == "timeout"
    assert outcome.trace.dense_hits == []
    assert outcome.trace.bm25_hits


@pytest.mark.asyncio
async def test_structural_chunks_are_returned_without_document_rechunk(monkeypatch) -> None:
    monkeypatch.setattr("app.ingestion.legal_text.chunk_document",
                        lambda *args, **kwargs: pytest.fail("rechunk called"))
    outcome = await retriever().retrieve("trách nhiệm môi trường")
    assert outcome.evidence[0].text == outcome.trace.final_hits[0].body
```

Also test dense instruction/BM25 raw query, exact document-number merge, malformed payload fail-closed, dedupe on record ID, max four per document, fused cap 64, rerank input/return limits, reranker error separation, provider usage, and opt-in factory rejection.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/services/test_structural_retrieval.py -q`

- [ ] **Step 3: Implement honest structural types and RRF**

```python
class StructuralSourceHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_id: str
    candidate: StructuralCandidate
    source_score: float


class StructuralCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_id: str
    document_id: int
    body: str
    document_number: str
    title: str
    source_url: str
    legal_type: str
    article: str | None
    clause: str | None
    citation: str
    token_count: int
    dataset_revision: str
    chunk_sha256: str
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    exact_rank: int | None = None
    fused_score: float = 0.0


def reciprocal_rank_fusion(*, dense, bm25, exact, rrf_k):
    by_id: dict[str, StructuralCandidate] = {}
    for source, hits in (("dense", dense), ("bm25", bm25), ("exact", exact)):
        for rank, hit in enumerate(hits, 1):
            current = by_id.get(hit.record_id, hit.candidate)
            current = current.model_copy(update={
                f"{source}_rank": rank,
                f"{source}_score": hit.source_score,
                "fused_score": current.fused_score + 1.0 / (rrf_k + rank),
            })
            by_id[hit.record_id] = current
    return sorted(by_id.values(), key=lambda row: (-row.fused_score, row.record_id))
```

The exact lane resolves normalized document numbers with existing local FTS, then performs a BM25 structural query restricted by the indexed `document_id` payload filter. This can introduce chunks absent from the unrestricted dense/BM25 top 48 while preserving an independent `exact_remote` error/usage record; it never claims full article/body FTS.

- [ ] **Step 4: Implement concurrent source retrieval and bounded reranking**

Implement `async def retrieve(self, query: str) -> StructuralRetrievalOutcome`. Run dense, BM25, and the conditional exact-filtered query with `asyncio.gather()` and `asyncio.to_thread()`. Dense uses the exact instruction document and `using="dense"`; both BM25 queries use the raw normalized query and `using="bm25"`. Validate payload/source revision before fusion. Preserve each source's receipt, latency, ranks, scores, and typed errors. A single-lane error yields `partial_technical_error`; both unrestricted remote lanes failing yields `retrieval_error` even if exact FTS has candidates.

After RRF, select at most four records per document and 64 total, convert to the existing reranker input contract, rerank, and return structural bodies directly as `CandidateChunk`. Record reranker provider/fallback identity and errors; do not hide a Qdrant reranker failure behind the Pinecone fallback label.

- [ ] **Step 5: Add opt-in factory without cutover**

```python
def build_structural_retriever(settings: Settings, *, client: QdrantClient,
                               fts_index: LegalFTSIndex,
                               reranker: RemoteReranker) -> StructuralRetriever:
    if not settings.STRUCTURAL_BACKEND_ENABLED:
        raise StructuralRetrievalError("structural backend is disabled")
    contract = StructuralQdrantContract.from_settings(settings)
    return StructuralRetriever(
        contract=contract,
        transport=StructuralQdrantTransport(client, contract),
        client=client,
        fts_index=fts_index,
        reranker=reranker,
    )
```

Do not edit `app/services/retrieval.py:get_legal_retriever()` or any API route.

- [ ] **Step 6: Run GREEN, review, and commit**

```powershell
python -m pytest tests/services/test_structural_retrieval.py tests/services/test_retrieval.py tests/services/test_remote_reranker.py -q
python -m ruff check app/services/structural_retrieval.py tests/services/test_structural_retrieval.py
git diff --check
git add app/services/structural_retrieval.py tests/services/test_structural_retrieval.py
git commit -m "feat(retrieval): add Qdrant structural retriever"
```

### Task 8: Reproducible structural benchmark, documentation, and final local proof

**Files:**
- Create: `app/evaluation/structural_pilot_eval.py`
- Create: `run_structural_retrieval_eval.py`
- Create: `tests/evaluation/test_structural_pilot_eval.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/evaluation/CURRENT_STATUS.md`
- Modify: `docs/superpowers/specs/2026-08-10-vietlex-qdrant-structural-pilot-design.md`
- Create: `docs/evaluation/index-pilots/<local-run-id>/manifest.json`
- Create: `docs/evaluation/index-pilots/<local-run-id>/scope.json`
- Create: `docs/evaluation/index-pilots/<local-run-id>/report.md`

**Interfaces:**
- Consumes: verified dataset/sidecar selection, Task 7 retriever, existing metric v3 match/aggregation functions, `prepare_run_directory()`, `write_immutable_json()`, and provenance utilities.
- Produces: honest `StructuralEvaluationTrace`, async `run_structural_pilot_evaluation()`, immutable `benchmark` run artifacts, `PASS_PILOT | FAIL_QUALITY | BLOCKED_TECHNICAL | BLOCKED_SCOPE`, and a provider-free local handoff plan.

- [ ] **Step 1: Add failing raw-trace, metric, and immutable-artifact tests**

```python
@pytest.mark.asyncio
async def test_raw_artifact_never_mislabels_structural_lanes(tmp_path) -> None:
    run = await run_structural_pilot_evaluation(fake_cases(), fake_retriever(), tmp_path)
    raw = json.loads((run.run_dir / "raw_results.json").read_text("utf-8"))
    trace = raw["cases"][0]["trace"]
    assert set(trace) >= {"dense_hits", "bm25_hits", "exact_hits", "fused_hits",
                          "reranker_input", "reranker_output", "final_hits"}
    assert "pinecone_hits" not in trace
    assert "fts_hits" not in trace


@pytest.mark.asyncio
async def test_report_includes_denominators_skips_errors_latency_and_usage(tmp_path) -> None:
    run = await run_structural_pilot_evaluation(fake_cases(), fake_retriever(), tmp_path)
    report = json.loads((run.run_dir / "report.json").read_text("utf-8"))
    assert report["metrics"]["fused_document_recall_at_24"]["denominator"] == 2
    assert report["coverage"]["skipped_cases"] == ["case-outside"]
    assert report["coverage"]["skip_reasons"] == {"outside_primary_legislation_scope": 1}
    assert report["technical_errors"]["dense"] == 0
    assert report["provider_usage"]["Qwen/Qwen3-Embedding-0.6B"] > 0


def test_pass_pilot_requires_material_p2_gain_and_zero_technical_errors() -> None:
    assert decide_pilot_acceptance(report(fused_document_recall_24=0.50,
                                          fused_article_recall_24=0.40,
                                          fused_clause_recall_24=0.30,
                                          technical_errors=0)) == "PASS_PILOT"
    assert decide_pilot_acceptance(report(fused_document_recall_24=0.0,
                                          fused_article_recall_24=0.0,
                                          fused_clause_recall_24=0.0,
                                          technical_errors=0)) == "FAIL_QUALITY"
```

Also test exact dataset/sidecar/verify/source hashes, unique run directory, raw error persistence, stage survival, exact-reference hits, multi-hop coverage, no-candidate rate, MRR, nDCG, no Ragas/generation/guardrail calls, artifact-only dirty-state recording, and source drift returning `BLOCKED_TECHNICAL`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_structural_pilot_eval.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 3: Implement structural trace and explicit metric adapter**

Keep raw names honest:

```python
class StructuralEvaluationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dense_hits: list[StageCandidate] = Field(default_factory=list)
    bm25_hits: list[StageCandidate] = Field(default_factory=list)
    exact_hits: list[StageCandidate] = Field(default_factory=list)
    fused_hits: list[StageCandidate] = Field(default_factory=list)
    reranker_input: list[StageCandidate] = Field(default_factory=list)
    reranker_output: list[StageCandidate] = Field(default_factory=list)
    final_hits: list[StageCandidate] = Field(default_factory=list)


def to_metric_v3_trace(trace: StructuralEvaluationTrace) -> RetrievalStageTrace:
    return RetrievalStageTrace(
        pinecone_hits=trace.dense_hits,
        fts_hits=trace.bm25_hits,
        merged_document_candidates=trace.fused_hits,
        resolved_document_candidates=trace.fused_hits,
        structural_chunks_generated=trace.fused_hits,
        locally_selected_chunks=trace.reranker_input,
        reranker_input_chunks=trace.reranker_input,
        reranker_output_chunks=trace.reranker_output,
        final_evidence_chunks=trace.final_hits,
    )
```

Use this adapter only inside existing metric v3 calls. Persist `metric_stage_aliases={"pinecone_hits":"dense_hits", "fts_hits":"bm25_hits", "merged_document_candidates":"fused_hits", "resolved_document_candidates":"fused_hits"}` in configuration/report so consumers cannot mistake providers. Raw artifacts always use structural names.

- [ ] **Step 4: Implement online/offline separation and acceptance**

Online execution only calls Task 7 and immediately stores typed per-case results/latencies/usage. Offline code computes Document/Article/Clause Recall@K, MRR, nDCG@10, exact-reference, all-required/partial-hop coverage, stage survival, no-candidate, retrieval/reranker technical errors, numerators, denominators, coverage, skipped IDs, and skip reasons. No semaphore is held during offline aggregation or artifact writing.

Acceptance precedence is exact:

```python
def decide_pilot_acceptance(report) -> str:
    if report.scope_error_count:
        return "BLOCKED_SCOPE"
    if report.technical_error_count or report.provenance_drift:
        return "BLOCKED_TECHNICAL"
    if (
        report.fused_document_recall_at_24 - report.p2_source_document_recall_at_24 >= 0.25
        and report.fused_article_recall_at_24 > 0.0
        and report.fused_clause_recall_at_24 > 0.0
    ):
        return "PASS_PILOT"
    return "FAIL_QUALITY"
```

No state claims production readiness or cutover authorization.

- [ ] **Step 5: Add `benchmark` CLI and immutable run files**

Require the exact `PASS_VERIFY` artifact and the immutable P2 baseline report. Validate that baseline and pilot dataset SHA, sidecar SHA, gold policy, and selected-case ID SHA are identical before comparing the first 24 fused structural source candidates with the first 24 P2 source candidates; mismatch returns `BLOCKED_SCOPE`. The absolute fused Document Recall@24 gain must be at least 0.25, while fused Article and Clause Recall@24 must both be nonzero. Write `docs/evaluation/runs/<run-id>/manifest.json`, `configuration.json`, `raw_results.json`, and `report.json` with exclusive creation. Include command, UTC, Git SHA/diff hash, dataset revision/SHA, sidecar SHA, plan/create/probe/upload/finalize/verify hashes, collection/vector/model/options/instruction, provider token counts, metric version, and every case status. Default command makes zero LLM-judge, generation, and guardrail calls.

- [ ] **Step 6: Update current source-of-truth documentation**

Mark the approved spec status `Approved; local implementation plan complete`. Document that Qdrant structural v2 is opt-in and code-prepared, while Pinecone v1 remains the production path. Record local tests actually executed and mark `create`, `probe-model`, `upload`, `finalize`, `verify`, and `benchmark` as `NOT RUN` unless the user later runs them successfully. Include exact user-run command templates populated from the generated local plan hash/source hash; do not include API keys.

- [ ] **Step 7: Generate the provider-free local artifact**

Run `audit` against the real pinned local content store. Run `plan` with the documented 4 GiB disk, 1 GiB RAM, 0.5 vCPU, and one shard, but leave `existing_disk_bytes` absent unless current cluster telemetry or the user supplies it; this must produce an honest `BLOCKED_CAPACITY` artifact instead of assuming zero existing usage. The artifact must reproduce 827 documents and 134,334 records; any drift stops the task and is reported rather than edited around.

- [ ] **Step 8: Run affected, full, static, and CLI verification once**

```powershell
python -m pytest tests/ingestion/test_structural_index.py tests/ingestion/test_structural_qdrant.py tests/ingestion/test_structural_pilot.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/evaluation/test_structural_model_probe.py tests/services/test_structural_retrieval.py tests/evaluation/test_structural_pilot_eval.py tests/evaluation/test_default_entrypoints.py -q
python -m pytest -q
python -m ruff check app tests run_structural_index_pilot.py run_structural_retrieval_eval.py
python -m compileall -q app run_structural_index_pilot.py run_structural_retrieval_eval.py
python run_structural_index_pilot.py --help
python run_structural_retrieval_eval.py --help
git diff --check
```

Run CRG `detect_changes`, inspect every high-impact path, confirm `get_legal_retriever()` is unchanged, confirm no remote mutation was executed, and record exact outputs. Any full-suite pre-existing failure remains visible with its exact test/error and does not become a false pass.

- [ ] **Step 9: Commit only after review is clean**

```powershell
git add app/evaluation/structural_pilot_eval.py run_structural_retrieval_eval.py tests/evaluation/test_structural_pilot_eval.py tests/evaluation/test_default_entrypoints.py docs/PROJECT_CONTEXT.md docs/CURRENT_ARCHITECTURE.md docs/evaluation/CURRENT_STATUS.md docs/superpowers/specs/2026-08-10-vietlex-qdrant-structural-pilot-design.md docs/evaluation/index-pilots
git commit -m "feat(eval): verify Qdrant structural pilot locally"
```

Final report lists changed files, every command/result, unit vs integration vs live-provider boundaries, `NOT RUN` remote phases, remaining limitations, and confirms no Pinecone/Qdrant/corpus/credential remote data was modified.
