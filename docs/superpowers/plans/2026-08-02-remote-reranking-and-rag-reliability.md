# Remote Reranking and RAG Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the local/Cloud Run reranker with remote Qdrant ColBERT plus Pinecone fallback, then correct the retrieval, failure reporting, evaluation, and startup latency defects identified in the technical report.

**Architecture:** Pinecone remains the durable hybrid vector store. A bounded Qdrant multivector staging collection performs remote ColBERT MaxSim reranking, while Pinecone Inference provides a transient fallback; SQLite FTS5 supplies exact legal-reference recall from the existing content store.

**Tech Stack:** Python 3.12, FastAPI, qdrant-client 1.18+, Pinecone Python SDK 9.x, SQLite FTS5, pytest/pytest-asyncio, Logfire.

## Global Constraints

- Never download or execute embedding, cross-encoder, ColBERT, FastEmbed, PyTorch, or ONNX models locally.
- Keep the durable 518,255-document corpus only in Pinecone; Qdrant contains bounded rerank staging points only.
- Keep all generated local indexes below `data/huggingface/` on drive D.
- Preserve the existing Pinecone embedding model `intfloat/multilingual-e5-small` and dimension 384.
- Do not rebuild or reingest the Pinecone index.
- Do not overwrite `docs/system_evaluation_report.md` or `docs/eval_checkpoints.json` during implementation tests.
- Load secrets only through `app/config.py`; never log provider keys or document text.

---

### Task 1: Remote reranking provider chain

**Files:**
- Create: `app/services/remote_reranker.py`
- Modify: `app/config.py`
- Modify: `app/services/clients.py`
- Modify: `.env.example`
- Test: `tests/services/test_remote_reranker.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `RerankResult(index: int, score: float)`, `RerankOutcome(results, provider, model, latency, fallback_reason)`, `RemoteReranker.rerank(query, documents)`.
- Consumes: injected Qdrant and Pinecone clients plus immutable `Settings`.

- [ ] **Step 1: Write failing configuration and provider tests**

```python
@pytest.mark.asyncio
async def test_qdrant_success_does_not_call_pinecone():
    outcome = await reranker.rerank("thuế", ["Điều 1", "Điều 2"])
    assert outcome.provider == "qdrant"
    assert [item.index for item in outcome.results] == [1, 0]
    assert pinecone.calls == []

@pytest.mark.asyncio
async def test_transient_qdrant_failure_falls_back_to_pinecone():
    outcome = await reranker.rerank("thuế", ["Điều 1"])
    assert outcome.provider == "pinecone"
    assert outcome.fallback_reason == "qdrant_transient"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/services/test_remote_reranker.py tests/test_config.py -q`

Expected: import/configuration failures because the provider chain does not exist.

- [ ] **Step 3: Implement Qdrant ColBERT staging and Pinecone fallback**

```python
@dataclass(frozen=True)
class RerankOutcome:
    results: list[RerankResult]
    provider: str
    model: str
    latency: float
    fallback_reason: str | None = None

class RemoteReranker:
    async def rerank(self, query: str, documents: list[str]) -> RerankOutcome:
        try:
            return await self._qdrant_rerank(query, documents)
        except Exception as error:
            if not is_transient_provider_error(error):
                raise
            return await self._pinecone_rerank(
                query, documents, fallback_reason="qdrant_transient"
            )
```

Create the Qdrant collection with a 96-dimensional `MultiVectorConfig(MAX_SIM)`, unique request IDs, payload filtering, one transient retry, and best-effort request-point deletion. Configure Pinecone `bge-reranker-v2-m3` with `return_documents=False`. Add a process-local consecutive-failure circuit breaker.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/services/test_remote_reranker.py tests/test_config.py -q`

Expected: all tests pass without network calls.

- [ ] **Step 5: Commit the provider chain**

```powershell
git add -- app/services/remote_reranker.py app/config.py app/services/clients.py .env.example tests/services/test_remote_reranker.py tests/test_config.py
git commit -m "feat: add remote reranking provider fallback"
```

### Task 2: Bounded candidate selection and retrieval diagnostics

**Files:**
- Modify: `app/services/retrieval.py`
- Modify: `tests/services/test_retrieval.py`

**Interfaces:**
- Consumes: `RemoteReranker.rerank(query, documents)` from Task 1.
- Produces: `RetrievalOutcome(status, evidence, latency, diagnostics, error)` and bounded candidate selection that normalizes query terms once.

- [ ] **Step 1: Write failing tests for provider integration and typed failures**

```python
@pytest.mark.asyncio
async def test_retrieval_records_remote_reranker_provider():
    outcome = await retriever.retrieve_detailed("khấu trừ thuế")
    assert outcome.status == "ok"
    assert outcome.diagnostics["rerank_provider"] == "qdrant"

@pytest.mark.asyncio
async def test_reranker_failure_is_not_no_candidate():
    outcome = await retriever.retrieve_detailed("khấu trừ thuế")
    assert outcome.status == "reranker_error"
    assert outcome.error
```

- [ ] **Step 2: Run the retrieval tests and verify RED**

Run: `python -m pytest tests/services/test_retrieval.py -q`

- [ ] **Step 3: Integrate the provider and optimize scoring**

```python
@dataclass(frozen=True)
class RetrievalOutcome:
    evidence: list[EvidenceChunk]
    latency: dict[str, float]
    status: str = "ok"
    diagnostics: dict[str, object] = field(default_factory=dict)
    error: str | None = None
```

Replace the Cloud Run HTTP call with the injected `RemoteReranker`. Compute `query_terms`, normalized query phrase, and cheap chunk terms once per selection call. Set `status="no_candidate"` only after successful retrieval with no chunks; set `retrieval_error` or `reranker_error` at the failing stage. Record top document IDs, candidate citations, reranked citations/scores, provider/model, and stage durations.

- [ ] **Step 4: Run retrieval tests and verify GREEN**

Run: `python -m pytest tests/services/test_retrieval.py -q`

- [ ] **Step 5: Commit bounded retrieval**

```powershell
git add -- app/services/retrieval.py tests/services/test_retrieval.py
git commit -m "perf: bound legal reranking and expose retrieval failures"
```

### Task 3: Exact legal-reference and FTS5 retrieval

**Files:**
- Create: `app/ingestion/legal_fts.py`
- Modify: `app/config.py`
- Modify: `app/services/retrieval.py`
- Create: `tests/ingestion/test_legal_fts.py`
- Modify: `tests/services/test_retrieval.py`

**Interfaces:**
- Produces: `LegalFtsIndex.ensure_built()`, `LegalFtsIndex.search(query, limit) -> list[int]`, and `extract_legal_references(query)`.
- Consumes: `ContentStore.get_many(document_ids)` and the existing content-store SQLite schema.

- [ ] **Step 1: Write failing exact-reference and merge tests**

```python
def test_exact_document_number_is_ranked_first(tmp_path):
    index = LegalFtsIndex(source_path, tmp_path / "legal_fts.sqlite3")
    index.ensure_built()
    assert index.search("Luật số 72/2020/QH14 Điều 15", limit=5)[0] == 431147

def test_lexical_and_pinecone_ids_are_merged_without_duplicates():
    assert merge_document_ids([431147, 7], [7, 9]) == [431147, 7, 9]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/ingestion/test_legal_fts.py tests/services/test_retrieval.py -q`

- [ ] **Step 3: Implement an incremental, drive-D FTS5 index**

```sql
CREATE VIRTUAL TABLE legal_fts USING fts5(
    document_id UNINDEXED,
    document_number,
    title,
    legal_type,
    issuing_authority,
    body,
    tokenize='unicode61 remove_diacritics 0'
);
```

Build atomically to a sibling temporary file, validate source revision/count, and replace only after `PRAGMA integrity_check` succeeds. Search exact normalized document-number matches first, then bounded FTS results. Merge lexical IDs before Pinecone IDs and resolve both through `ContentStore`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/ingestion/test_legal_fts.py tests/services/test_retrieval.py -q`

- [ ] **Step 5: Commit exact retrieval**

```powershell
git add -- app/ingestion/legal_fts.py app/config.py app/services/retrieval.py tests/ingestion/test_legal_fts.py tests/services/test_retrieval.py
git commit -m "feat: add exact legal reference retrieval"
```

### Task 4: Propagate retrieval failures through the RAG pipeline

**Files:**
- Modify: `app/services/rag_pipeline.py`
- Modify: `tests/test_rag_pipeline.py`

**Interfaces:**
- Consumes: typed `RetrievalOutcome` from Task 2.
- Produces: latency metadata containing `retrieval_status`, diagnostics, rewritten query, and technical error; technical failures raise `RetrievalPipelineError`.

- [ ] **Step 1: Write a failing service-error test**

```python
@pytest.mark.asyncio
async def test_pipeline_does_not_turn_retrieval_error_into_honest_refusal():
    with pytest.raises(rag_pipeline.RetrievalPipelineError):
        await rag_pipeline.run_advanced_rag("điều kiện thuế")
```

- [ ] **Step 2: Run the pipeline tests and verify RED**

Run: `python -m pytest tests/test_rag_pipeline.py -q`

- [ ] **Step 3: Implement error propagation and bounded context defaults**

```python
if retrieval_outcome.status in {"retrieval_error", "reranker_error"}:
    raise RetrievalPipelineError(
        retrieval_outcome.status,
        retrieval_outcome.error or "Legal retrieval failed.",
        retrieval_outcome.diagnostics,
    )
```

Keep the public no-evidence response only for `no_candidate`, add rewritten query and provider diagnostics to latency metadata, and change default context budget to 720 tokens.

- [ ] **Step 4: Run pipeline tests and verify GREEN**

Run: `python -m pytest tests/test_rag_pipeline.py -q`

- [ ] **Step 5: Commit error propagation**

```powershell
git add -- app/services/rag_pipeline.py tests/test_rag_pipeline.py
git commit -m "fix: distinguish retrieval errors from legal refusals"
```

### Task 5: Guardrail startup warm-up and output audit

**Files:**
- Modify: `app/services/guardrails.py`
- Modify: `app/main.py`
- Create: `tests/services/test_guardrails.py`

**Interfaces:**
- Produces: `warm_guardrails() -> None` and structured log fields for output blocking.

- [ ] **Step 1: Write failing warm-up and audit tests**

```python
@pytest.mark.asyncio
async def test_warm_guardrails_initializes_off_event_loop(monkeypatch):
    await guardrails.warm_guardrails()
    assert calls == ["get_rails"]

@pytest.mark.asyncio
async def test_output_block_log_keeps_hash_not_raw_answer(caplog):
    safe, _ = await guardrails.check_output_guardrails("unsafe", ["ctx"], "q")
    assert safe is False
    assert "response_sha256" in caplog.text
    assert "unsafe" not in caplog.text
```

- [ ] **Step 2: Run the guardrail tests and verify RED**

Run: `python -m pytest tests/services/test_guardrails.py -q`

- [ ] **Step 3: Warm NeMo during startup**

```python
async def warm_guardrails() -> None:
    await asyncio.to_thread(get_rails)
```

Call it from the FastAPI startup event. Hash the pre-block response for correlation and log only its hash, evidence citations, and outcome—never raw private content.

- [ ] **Step 4: Run guardrail tests and verify GREEN**

Run: `python -m pytest tests/services/test_guardrails.py -q`

- [ ] **Step 5: Commit startup latency changes**

```powershell
git add -- app/services/guardrails.py app/main.py tests/services/test_guardrails.py
git commit -m "perf: warm guardrails before serving requests"
```

### Task 6: Correct golden evaluation metrics and timings

**Files:**
- Modify: `run_eval_suite.py`
- Modify: `tests/test_run_eval_suite.py`

**Interfaces:**
- Produces: interleaved dataset selection, exact evaluator errors, true wall latency, queue latency, retrieval hit metrics, and a correct outcome matrix.

- [ ] **Step 1: Write failing metric and scheduling tests**

```python
def test_selected_cases_are_interleaved_by_group():
    groups = [case["group"] for case in selected[:6]]
    assert groups == ["Factoid", "Multi-hop", "Unanswerable"] * 2

def test_answerable_block_is_not_counted_as_correct_refusal():
    metrics = summarize_outcomes([blocked_answerable])
    assert metrics["answerable_correct"] == 0

def test_reference_context_hit_reports_recall_and_mrr():
    metrics = retrieval_metrics(retrieved, reference_contexts)
    assert metrics == {"gold_context_hit": True, "reciprocal_rank": 0.5}
```

- [ ] **Step 2: Run evaluator tests and verify RED**

Run: `python -m pytest tests/test_run_eval_suite.py -q`

- [ ] **Step 3: Implement corrected measurement**

Start total timing before semaphore acquisition, record `queue_latency`, pipeline stages, guardrails, Ragas, and final wall time. Preserve the exact Ragas exception. Classify `No Evidence` before refusal keyword matching, compute answerable/unanswerable denominators separately, and use normalized reference-context overlap for direct retrieval hit and reciprocal rank.

- [ ] **Step 4: Run evaluator tests and verify GREEN**

Run: `python -m pytest tests/test_run_eval_suite.py -q`

- [ ] **Step 5: Commit evaluator corrections**

```powershell
git add -- run_eval_suite.py tests/test_run_eval_suite.py
git commit -m "fix: report valid RAG evaluation metrics"
```

### Task 7: Documentation and complete verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Test: full test suite

**Interfaces:**
- Documents: provider order, no-local-model guarantee, Qdrant staging capacity, FTS build behavior, failure semantics, and evaluation commands.

- [ ] **Step 1: Update README architecture and operations**

Document Qdrant ColBERT primary, Pinecone BGE fallback, candidate/token budgets, FTS5 location, startup behavior, provider configuration, and the third-party dataset disclaimer. Remove all Cloud Run/local reranker instructions.

- [ ] **Step 2: Verify no local model or retired reranker remains**

Run: `rg -n "RERANK_API_URL|EMBEDDING_SERVICE_API_KEY|sentence_transformers|CrossEncoder|fastembed|torch" app README.md .env.example`

Expected: no production references to the retired Cloud Run or local model paths; Qdrant documentation references to FastEmbed are not added.

- [ ] **Step 3: Run the complete offline test suite**

Run: `python -m pytest -q`

Expected: all tests pass without Qdrant, Pinecone, Ragas judge, or LLM network calls.

- [ ] **Step 4: Review impact and dirty-file boundaries**

Run: `git status --short`

Expected: user-owned `docs/system_evaluation_report.md` and `docs/eval_checkpoints.json` remain unstaged and unchanged by implementation; only intentional documentation/code changes are committed.

- [ ] **Step 5: Commit documentation**

```powershell
git add -- README.md .env.example
git commit -m "docs: document remote reranking and reliable evaluation"
```

- [ ] **Step 6: Do not run live smoke tests without explicit authorization**

Provide the user with one Qdrant/Pinecone smoke command and the golden evaluation command. The user runs them to conserve API quota.
