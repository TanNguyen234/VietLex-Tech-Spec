# VietLex Structural Pinecone Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dry-run-first structural retrieval pilot that uses only Pinecone-hosted embeddings, indexes a deterministic primary-legislation corpus, and can be benchmarked without modifying the v1 index.

**Architecture:** A pure local layer selects and chunks the pinned corpus and produces a hash-bound manifest. A typed Pinecone adapter validates the hosted model contract and owns all remote calls. A separate pilot controller creates/upserts a new document-schema index only behind an exact remote-write gate, while a standalone structural retriever performs dense and BM25 searches and merges them deterministically. The production v1 retriever remains the default until a live pilot passes.

**Tech Stack:** Python 3.12, Pydantic settings/models, SQLite/Zstandard content store, Pinecone SDK 9.x and Pinecone Inference, pytest, Ruff, CRG.

## Global Constraints

- Do not use Qdrant or any local model for pilot query or passage embeddings.
- Use Pinecone-hosted `llama-text-embed-v2`, dimension `1024`, cosine, `input_type=query|passage`.
- Pilot corpus types are exactly `Hiến pháp`, `Luật`, and `Pháp lệnh`; never select documents by gold IDs.
- Chunk limit is `420` approximate whitespace tokens with `48` overlap only for oversized structural units.
- Pilot target is a new index `vietlex-legal-rag-v2-pilot` and namespace `national-primary-v1`.
- Default commands are read-only/dry-run. Remote creation/upsert requires the exact target plus `--execute-remote-writes`.
- No implementation path may delete, clear, or reconfigure `vietlex-legal-rag-v1`.
- Worktree creation is OFF unless the user explicitly requests it.
- Provider errors must remain typed and observable; do not silently fall back to another model or dimension.
- Every artifact includes Git/source-state, dataset revision, scope predicate, selected-ID hash, model contract, and provider-call count.

---

### Task 1: Deterministic primary-legislation scope and structural records

**Files:**
- Create: `app/ingestion/structural_index.py`
- Test: `tests/ingestion/test_structural_index.py`

**Interfaces:**
- Consumes: `ContentStore.iter_document_ids_by_legal_types()`, `ContentStore.get_many()`, `chunk_document()`.
- Produces: `PRIMARY_LEGAL_TYPES`, `StructuralRecord`, `StructuralCorpusManifest`, `select_structural_document_ids()`, `build_structural_records()`, and `build_structural_manifest()`.

- [ ] **Step 1: Write failing scope and identity tests**

```python
def test_primary_scope_is_type_based_sorted_and_gold_agnostic():
    store = FakeStore(types={3: "Luật", 1: "Công văn", 2: "Hiến pháp"})
    assert select_structural_document_ids(store) == [2, 3]
    assert store.requested_types == ("Hiến pháp", "Luật", "Pháp lệnh")

def test_structural_record_identity_changes_with_chunk_text_not_order():
    first = build_structural_records(store, [10])
    second = build_structural_records(store, [10])
    assert [row.record_id for row in first] == [row.record_id for row in second]
    assert len({row.record_id for row in first}) == len(first)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_index.py -q`

Expected: collection fails because `app.ingestion.structural_index` does not exist.

- [ ] **Step 3: Implement the pure contracts**

```python
PRIMARY_LEGAL_TYPES = ("Hiến pháp", "Luật", "Pháp lệnh")

class StructuralRecord(BaseModel):
    record_id: str
    body: str
    document_id: int
    document_number: str
    title: str
    source_url: str
    legal_type: str
    issuing_authority: str
    issuance_date: str | None
    article: str | None
    clause: str | None
    heading_path: str
    citation: str
    dataset_revision: str
    content_sha256: str
    chunk_sha256: str

def select_structural_document_ids(store: ContentStore) -> list[int]:
    selected: list[int] = []
    after_id = -1
    while True:
        page = store.iter_document_ids_by_legal_types(
            PRIMARY_LEGAL_TYPES, after_id=after_id, limit=512
        )
        if not page:
            return selected
        if page != sorted(set(page)) or any(value <= after_id for value in page):
            raise StructuralIndexError("invalid structural corpus page")
        selected.extend(page)
        after_id = page[-1]

def build_structural_records(
    store: ContentStore,
    document_ids: Sequence[int],
    *,
    repository: str,
    revision: str,
    max_tokens: int = 420,
    overlap_tokens: int = 48,
) -> list[StructuralRecord]:
    records: list[StructuralRecord] = []
    for document_id in document_ids:
        document = store.get_many([document_id]).get(document_id)
        if document is None:
            raise StructuralIndexError(f"missing document {document_id}")
        chunks = chunk_document(
            document.metadata,
            document.content,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )
        for chunk in chunks:
            chunk_sha = sha256_text(chunk.text)
            record_id = str(uuid5(
                NAMESPACE_URL,
                f"{repository}@{revision}#{document_id}:{chunk.citation}:{chunk_sha}",
            ))
            records.append(StructuralRecord.from_chunk(
                record_id=record_id,
                chunk=chunk,
                document=document,
                dataset_revision=revision,
                chunk_sha256=chunk_sha,
            ))
    if len({row.record_id for row in records}) != len(records):
        raise StructuralIndexError("structural record ID collision")
    return records
```

The manifest must contain document/record counts, per-type counts, raw content bytes, selected document IDs SHA-256, ordered record IDs SHA-256, chunk-token parameters, and zero provider calls. It must not contain document bodies.

- [ ] **Step 4: Add fail-closed tests**

Cover duplicate IDs, unsorted pages, missing documents, content hash mismatch, blank chunks, record-ID collision, unsupported legal type, and noncanonical SHA-256.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/ingestion/test_structural_index.py -q`

Then:

```powershell
git add -- app/ingestion/structural_index.py tests/ingestion/test_structural_index.py
git commit -m "feat(ingestion): define structural pilot corpus"
```

### Task 2: Pinecone-hosted embedding contract

**Files:**
- Create: `app/services/pinecone_embeddings.py`
- Modify: `app/config.py`
- Test: `tests/services/test_pinecone_embeddings.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Pinecone control client `inference.get_model()` and `inference.embed()`.
- Produces: `HostedEmbeddingContract`, `PineconeHostedEmbedder.describe_and_validate()`, `embed_queries()`, and `embed_passages()`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_embedder_requires_exact_hosted_model_dimension_and_input_type():
    client = FakePinecone(model_info=LLAMA_MODEL_INFO)
    embedder = PineconeHostedEmbedder(client, HostedEmbeddingContract())
    assert len(embedder.embed_queries(["câu hỏi"])[0]) == 1024
    assert client.embed_calls[0].parameters == {
        "input_type": "query", "truncate": "END", "dimension": 1024,
    }

@pytest.mark.parametrize("actual", [384, 768, 2048])
def test_embedder_rejects_wrong_vector_dimension(actual):
    with pytest.raises(HostedEmbeddingError, match="dimension"):
        embedder_with_vector_size(actual).embed_passages(["đoạn luật"])
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/services/test_pinecone_embeddings.py tests/test_config.py -q`

Expected: missing module/settings failures.

- [ ] **Step 3: Add opt-in configuration**

Add settings without changing v1 defaults:

```python
STRUCTURAL_INDEX_NAME: str = "vietlex-legal-rag-v2-pilot"
STRUCTURAL_NAMESPACE: str = "national-primary-v1"
STRUCTURAL_EMBEDDING_MODEL: str = "llama-text-embed-v2"
STRUCTURAL_EMBEDDING_DIMENSION: int = 1024
STRUCTURAL_CHUNK_MAX_TOKENS: int = 420
STRUCTURAL_CHUNK_OVERLAP_TOKENS: int = 48
STRUCTURAL_EMBED_BATCH_SIZE: int = 96
STRUCTURAL_BACKEND_ENABLED: bool = False
```

Validate the fixed pilot contract at model construction. Never reuse `DENSE_INFERENCE_MODEL` or the Qdrant client.

- [ ] **Step 4: Implement typed response validation and usage accounting**

```python
@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    dimension: int
    input_type: Literal["query", "passage"]
    total_tokens: int
    provider_calls: int = 1
```

Reject missing/extra vectors, non-finite values, mismatched dimensions, model drift, unsupported parameters, and absent usage. Retry only provider-declared transient failures with bounded attempts; surface the original category/message.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/services/test_pinecone_embeddings.py tests/test_config.py -q`

Then commit only Task 2 files with `feat(retrieval): add Pinecone hosted embeddings`.

### Task 3: Dry-run-first pilot planner and remote-write gate

**Files:**
- Create: `app/ingestion/structural_pilot.py`
- Create: `run_structural_index_pilot.py`
- Test: `tests/ingestion/test_structural_pilot.py`
- Test: `tests/evaluation/test_default_entrypoints.py`

**Interfaces:**
- Consumes: Task 1 manifest/records and Task 2 embedder.
- Produces: `PilotPlan`, `RemoteWriteAuthorization`, `build_pilot_plan()`, `create_pilot_index()`, `upsert_pilot_batches()`, and CLI phases `plan`, `create`, `upsert`, `verify`.

- [ ] **Step 1: Write failing authorization tests**

```python
def test_plan_is_provider_free_and_contains_no_bodies(tmp_path):
    plan = build_pilot_plan(settings, fake_store)
    assert plan.provider_calls == 0
    assert "ground truth" not in plan.model_dump_json().casefold()

@pytest.mark.parametrize("phase", ["create", "upsert"])
def test_remote_phase_requires_exact_target_and_explicit_flag(phase, runner):
    result = runner.invoke(cli, [phase])
    assert result.exit_code != 0
    assert fake_pinecone.mutations == []
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/ingestion/test_structural_pilot.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 3: Implement immutable planning output**

`plan` writes a unique directory under `docs/evaluation/index-pilots/<run-id>/` with `manifest.json`, `scope.json`, and `report.md`. It uses exclusive directory creation, canonical JSON, artifact SHA-256, and Git provenance. If the tree is dirty, it records the diff hash and cannot authorize a remote phase.

- [ ] **Step 4: Implement exact remote gate**

```python
class RemoteWriteAuthorization(BaseModel):
    execute_remote_writes: Literal[True]
    index_name: Literal["vietlex-legal-rag-v2-pilot"]
    namespace: Literal["national-primary-v1"]
    manifest_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
```

`create` must fail if the index already exists, if v1 is named, if the model description differs, or if the source tree/manifest changed. Create a document-schema index with `body` BM25 and `embedding` dense-vector 1024/cosine. Do not expose a delete operation.

`upsert` must embed record bodies with Task 2 and submit batches of at most 96 records. Checkpoint completion by deterministic record ID and artifact hash; a retry must never silently skip a failed batch.

- [ ] **Step 5: Implement verification**

`verify` checks remote index schema, namespace count, exact pilot record count, and deterministic samples of record metadata/chunk hashes. It writes a new immutable verification artifact and does not update the plan artifact.

- [ ] **Step 6: Run GREEN, CLI help, and commit**

Run:

```powershell
python -m pytest tests/ingestion/test_structural_pilot.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_index_pilot.py --help
python run_structural_index_pilot.py plan --help
```

Commit only Task 3 files with `feat(ingestion): add gated structural pilot`.

### Task 4: Structural dense/BM25 retrieval without production cutover

**Files:**
- Create: `app/services/structural_retrieval.py`
- Test: `tests/services/test_structural_retrieval.py`

**Interfaces:**
- Consumes: Task 2 query embedder and a Pinecone document-index client.
- Produces: `StructuralCandidate`, `StructuralRetrievalOutcome`, `reciprocal_rank_fusion()`, and `StructuralRetriever.retrieve()`.

- [ ] **Step 1: Write failing merge and error tests**

```python
def test_rrf_preserves_exact_source_ranks_and_deduplicates():
    merged = reciprocal_rank_fusion(dense=[hit("a"), hit("b")], lexical=[hit("b"), hit("c")])
    assert [row.record_id for row in merged] == ["b", "a", "c"]
    assert merged[0].dense_rank == 2
    assert merged[0].lexical_rank == 1

def test_retriever_exposes_embedding_dense_and_bm25_failures_separately():
    outcome = retriever_with_bm25_failure().retrieve("Điều 16 môi trường")
    assert outcome.technical_errors["bm25"][0].category == "ProviderError"
    assert outcome.technical_errors["dense"] == []
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/services/test_structural_retrieval.py -q`

- [ ] **Step 3: Implement bounded source retrieval**

Dense and BM25 requests each use a configurable top-k of 48. Merge with RRF constant 60, keep source scores/ranks, deduplicate on record ID, then balance at most four chunks per document into a maximum of 64 rerank inputs. Validate every returned record against the pilot model, dimension, dataset revision, scope revision, and required metadata.

Do not call the existing full-document resolver or `chunk_document()` at query time; pilot records are already structural chunks.

- [ ] **Step 4: Add opt-in factory only**

Provide `build_structural_retriever(settings: Settings, *, index: object, embedder: PineconeHostedEmbedder) -> StructuralRetriever` that raises unless `STRUCTURAL_BACKEND_ENABLED=true`. Do not edit `get_retriever()` or switch production API routes in this task.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/services/test_structural_retrieval.py tests/services/test_retrieval.py -q`

Commit only Task 4 files with `feat(retrieval): add structural pilot retriever`.

### Task 5: Reproducible pilot evaluation and model smoke artifacts

**Files:**
- Create: `run_structural_retrieval_eval.py`
- Create: `app/evaluation/structural_pilot.py`
- Test: `tests/evaluation/test_structural_pilot.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`

**Interfaces:**
- Consumes: Task 4 retriever, existing verified dataset/sidecar loaders, retrieval metrics v3, and provenance utilities.
- Produces: immutable pilot run artifacts and an optional provider-only model smoke report.

- [ ] **Step 1: Write failing artifact tests**

Test exact case IDs, dataset/sidecar SHA, source-state SHA, index/namespace/model/dimension/scope, provider call/token counts, raw candidate stages, numerator/denominator/coverage/skips, and exclusive run directories. A partial provider failure must still persist an honest failed run with typed error records.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_structural_pilot.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 3: Implement two explicit modes**

`model-smoke` embeds the selected questions/passages with Pinecone-hosted models and persists ranks without writing an index. `retrieval` requires a verified pilot artifact and runs the same selected case set through Task 4. Neither mode calls generation, guardrails, Ragas, Qdrant, or a local model.

- [ ] **Step 4: Add acceptance decision**

The report must set one of:

- `PASS_PILOT`: non-zero document/article/clause recall, no provenance drift, no technical errors, and improved Document Recall@24 over P2;
- `FAIL_RETRIEVAL`: valid run but no material recall gain;
- `BLOCKED_TECHNICAL`: provider/schema/provenance failure;
- `BLOCKED_SCOPE`: gold evidence absent from the declared pilot scope.

No result may claim production readiness.

- [ ] **Step 5: Run GREEN and commit**

Run:

```powershell
python -m pytest tests/evaluation/test_structural_pilot.py tests/evaluation/test_default_entrypoints.py -q
python run_structural_retrieval_eval.py --help
```

Commit only Task 5 files with `feat(eval): evaluate structural Pinecone pilot`.

### Task 6: Local integration verification and remote handoff

**Files:**
- Modify: `docs/evaluation/CURRENT_STATUS.md`
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Create: `docs/evaluation/index-pilots/<local-plan-run-id>/manifest.json`
- Create: `docs/evaluation/index-pilots/<local-plan-run-id>/scope.json`
- Create: `docs/evaluation/index-pilots/<local-plan-run-id>/report.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: a provider-free local pilot plan and a precise remote command that cannot target v1.

- [ ] **Step 1: Run provider-free plan**

Run:

```powershell
python run_structural_index_pilot.py plan --require-clean-git --run-id <unique-local-plan-run-id>
```

Verify 827 selected documents, exact legal-type counts, non-zero structural record count, provider calls 0, no raw body in artifacts, and correct Git/dataset hashes.

- [ ] **Step 2: Run focused and broad suites**

Run:

```powershell
python -m pytest tests/ingestion/test_structural_index.py tests/services/test_pinecone_embeddings.py tests/ingestion/test_structural_pilot.py tests/services/test_structural_retrieval.py tests/evaluation/test_structural_pilot.py -q
python -m pytest tests/ingestion tests/services tests/evaluation -q
python -m pytest -q
```

- [ ] **Step 3: Run static and graph review**

Run Ruff E4/E7/E9/F over changed Python files, `python -m compileall` over changed modules/entrypoints, and `git diff --check`. Update CRG incrementally, inspect detected changes and impact radius, then source-validate all graph findings.

- [ ] **Step 4: Update source-of-truth docs**

Document that v1 remains active and failed, v2 is an unexecuted pilot unless a live write actually occurred, the exact reduced scope, model/dimension, Pinecone-only embedding boundary, public-preview FTS limitation, and all `NOT RUN` live operations.

- [ ] **Step 5: Commit the verified local implementation**

Commit implementation and local artifacts with a scoped message only after all required checks pass. Do not push. Do not create, write, switch, or delete a remote index in this step.

## Deferred plan boundary

Production cutover and full-scope ingestion are deliberately not part of this plan. After a live pilot has an immutable `PASS_PILOT` result and an actual storage-per-record measurement, write a separate plan covering quota math, expansion scope, v1 retirement/rollback, production backend switch, and the exact destructive authorization if v1 must be deleted.
