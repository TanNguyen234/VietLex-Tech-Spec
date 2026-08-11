# VietLex Structural Recall Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 827-document Qdrant structural pilot a trustworthy, no-paid-default path capable of demonstrating recall close to 1.0 without selecting the corpus from golden labels.

**Architecture:** Preserve the existing immutable `audit -> plan -> create -> probe-model -> upload -> finalize -> verify -> benchmark` workflow. Enrich only the versioned inference text, make the bounded model probe discriminate against deterministic real corpus negatives and canaries, remove mandatory Pinecone inference, and tighten final quality gates. Keep worktree creation off and do not execute remote phases.

**Tech Stack:** Python 3.12, Pydantic v2, Qdrant Client/Cloud Inference, SQLite/Zstandard content store, pytest, Ruff, CRG.

## Global Constraints

- Corpus scope is all and only `Hiến pháp`, `Luật`, and `Pháp lệnh` rows from the pinned 518,255-document snapshot; golden labels never select corpus membership.
- Default provider path uses Qdrant Cloud Inference only; no local embedding and no live Pinecone reference call.
- Stored evidence body is unchanged; only a versioned deterministic inference text is enriched.
- Collection creation/deletion, upload, finalize, verify, and benchmark are `NOT RUN` by Codex; the user executes remote phases.
- No production retriever cutover, Pinecone/Qdrant deletion, generation, Ragas, or guardrail work.
- Full quality PASS requires Document Recall@24 `1.0`, applicable Article Recall@24 at least `0.95`, applicable Clause Recall@24 at least `0.90`, all-required coverage at least `0.95`, and zero technical-error/no-candidate rates.

## File map

- `app/config.py`: declares the exact inference-text version.
- `app/ingestion/structural_qdrant.py`: builds and hashes dense/BM25 document text and binds it into the Qdrant contract/payload.
- `app/ingestion/structural_checkpoint.py`: includes inference-text identity in resumable acknowledgement.
- `app/ingestion/structural_upload.py`: propagates the stronger checkpoint identity without changing retry/concurrency behavior.
- `app/ingestion/structural_pilot.py`: reads back the new contract/hash and retains fail-closed capacity/schema verification.
- `app/evaluation/structural_model_probe.py`: builds real corpus-wide distractors/canaries and evaluates absolute Qdrant gates without mandatory Pinecone inference.
- `app/evaluation/structural_pilot_eval.py`: enforces the final recall≈1 acceptance contract and reports reranker contribution.
- `run_structural_index_pilot.py`: defaults `probe-model` to Qdrant-only and makes immutable reference comparison optional.
- Existing focused tests under `tests/ingestion/`, `tests/evaluation/`, and `tests/services/` are extended; no new test framework is introduced.

---

### Task 1: Versioned inference text and resumable identity

**Files:**
- Modify: `app/config.py`
- Modify: `app/ingestion/structural_qdrant.py`
- Modify: `app/ingestion/structural_checkpoint.py`
- Modify: `app/ingestion/structural_upload.py`
- Modify: `app/ingestion/structural_pilot.py`
- Modify: `tests/test_config.py`
- Modify: `tests/ingestion/test_structural_qdrant.py`
- Modify: `tests/ingestion/test_structural_checkpoint.py`
- Modify: `tests/ingestion/test_structural_upload.py`
- Modify: `tests/ingestion/test_structural_pilot.py`

**Interfaces:**
- Produces: `build_structural_inference_text(record: StructuralRecord) -> str`
- Produces: `structural_inference_text_sha256(record: StructuralRecord) -> str`
- Extends: `StructuralQdrantContract.document_text_version == "vietlex-structural-document-v2"`
- Extends payload/checkpoint acknowledgement with `inference_text_sha256`.

- [ ] **Step 1: Write failing inference-text contract tests**

```python
def test_inference_text_contains_provenance_structure_and_unchanged_body() -> None:
    text = build_structural_inference_text(structural_record())
    assert text == (
        "Tiêu đề: Luật mẫu\n"
        "Số văn bản: 01/2026/QH15\n"
        "Loại văn bản: Luật\n"
        "Cấu trúc: Chương I > Điều 1\n"
        "Trích dẫn: 01/2026/QH15, Điều 1\n"
        "Nội dung:\nĐiều 1. Phạm vi điều chỉnh"
    )
    assert point_from_record(structural_record(), contract()).payload[
        "inference_text_sha256"
    ] == hashlib.sha256(text.encode("utf-8")).hexdigest()
```

Also assert dense and BM25 `models.Document.text` are the exact same enriched text, blank optional headings are omitted, contract drift is rejected, and body/chunk hashes remain unchanged.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_config.py tests/ingestion/test_structural_qdrant.py -q`

Expected: failures for missing document-text version, builder, and payload hash.

- [ ] **Step 3: Implement the minimal deterministic builder**

```python
def build_structural_inference_text(record: StructuralRecord) -> str:
    structure = record.heading_path.strip() or record.citation.strip()
    fields = (
        ("Tiêu đề", record.title),
        ("Số văn bản", record.document_number),
        ("Loại văn bản", record.legal_type),
        ("Cấu trúc", structure),
        ("Trích dẫn", record.citation),
    )
    header = "\n".join(f"{name}: {' '.join(value.split())}" for name, value in fields if value.strip())
    return f"{header}\nNội dung:\n{record.body}"
```

Pass this text to both Qdrant inference documents. Bind the version in the immutable contract and add the SHA-256 to payload, acknowledged-record identity, batch identity, upload receipt validation, and deterministic verification sample.

- [ ] **Step 4: Run Task 1 GREEN**

Run:

```powershell
python -m pytest tests/test_config.py tests/ingestion/test_structural_qdrant.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py -q
```

Expected: all selected tests pass; no remote client is constructed.

- [ ] **Step 5: Review and commit Task 1**

```powershell
python -m ruff check app/config.py app/ingestion/structural_qdrant.py app/ingestion/structural_checkpoint.py app/ingestion/structural_upload.py app/ingestion/structural_pilot.py tests/test_config.py tests/ingestion/test_structural_qdrant.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py
git diff --check
git add app/config.py app/ingestion/structural_qdrant.py app/ingestion/structural_checkpoint.py app/ingestion/structural_upload.py app/ingestion/structural_pilot.py tests/test_config.py tests/ingestion/test_structural_qdrant.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py
git commit -m "feat(ingestion): bind structural inference text"
```

### Task 2: Real hard negatives and corpus canaries

**Files:**
- Modify: `app/evaluation/structural_model_probe.py`
- Modify: `tests/evaluation/test_structural_model_probe.py`

**Interfaces:**
- Extends: `StructuralProbeSelection` with `relevant_record_ids`, `hard_negative_record_ids`, and `canary_queries`.
- Produces: `StructuralCanary(query_id: str, query: str, document_id: int, legal_type: str)`.
- Produces: deterministic sampling version `primary-scope-hard-negatives-v1`.

- [ ] **Step 1: Write failing selection tests**

```python
def test_probe_selection_includes_one_real_negative_per_non_gold_document() -> None:
    selection = select_model_probe_records(cases(), records_from_four_documents())
    assert {row.document_id for row in selection.records} == {1, 2, 3, 4}
    assert len(selection.hard_negative_record_ids) == 2
    assert selection.synthetic_records == 0

def test_probe_selection_is_stable_when_record_iteration_order_changes() -> None:
    assert selection_hash(records()) == selection_hash(reversed(records()))
```

Also test one negative per non-gold document, representative selection by lowest SHA-256 of `record_id`, canary stratification by legal type and ID quantile, title normalization with document number removed, no case/record overlap ambiguity, and exact hashes/counts in report serialization.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_structural_model_probe.py -q`

Expected: missing distractor/canary fields and relevant-only selection assertions fail.

- [ ] **Step 3: Implement deterministic real-record selection**

For each non-gold document retain the record minimizing
`sha256("primary-scope-hard-negatives-v1:" + record_id)`. Select 64 canary documents by stratified legal type and stable SHA order; each query is the normalized title after removing the exact document number. Exclude blank/duplicate queries and persist exclusions with typed reasons. Do not generate prose or labels with a model.

- [ ] **Step 4: Extend rank metrics without mixing denominators**

Keep verified-question metrics and canary metrics separate:

```python
gold_metrics = metrics_from_matches(gold_ranks, ks=(1, 3, 10))
canary_metrics = document_metrics_from_ranks(canary_ranks, ks=(1, 3, 10))
```

Never add canaries to the 40-case golden denominator.

- [ ] **Step 5: Run Task 2 GREEN and commit**

```powershell
python -m pytest tests/evaluation/test_structural_model_probe.py tests/ingestion/test_structural_index.py -q
python -m ruff check app/evaluation/structural_model_probe.py tests/evaluation/test_structural_model_probe.py
git diff --check
git add app/evaluation/structural_model_probe.py tests/evaluation/test_structural_model_probe.py
git commit -m "test(eval): add corpus-wide structural probe negatives"
```

### Task 3: Qdrant-only model probe with absolute gates

**Files:**
- Modify: `app/evaluation/structural_model_probe.py`
- Modify: `run_structural_index_pilot.py`
- Modify: `tests/evaluation/test_structural_model_probe.py`
- Modify: `tests/evaluation/test_default_entrypoints.py`

**Interfaces:**
- Changes: `run_structural_model_probe(transport, probe, reference_embedder=None)`.
- Keeps: `--reference-probe` as an optional immutable audit input.
- Removes: automatic `Pinecone(...)` construction from default `probe-model`.
- Produces absolute gold and canary gate fields in schema version `2.0.0`.

- [ ] **Step 1: Write failing no-Pinecone tests**

```python
def test_probe_cli_does_not_construct_pinecone_without_reference(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pinecone", forbidden_module())
    assert run_bound_probe(arguments(reference_probe=None), fake_qdrant()) in {0, 4}

def test_probe_pass_requires_gold_and_canary_absolute_gates() -> None:
    assert decide_probe_acceptance(
        gold_document_recall_10=1.0,
        gold_structural_recall_10=0.95,
        canary_document_recall_10=0.90,
        technical_errors=0,
    ) == "PASS_MODEL_PROBE"
```

Also test each threshold just below the boundary, optional static-reference hash binding, candidate provider usage containing only the two Qdrant models, and no provider client construction before all local/artifact bindings pass.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/evaluation/test_structural_model_probe.py tests/evaluation/test_default_entrypoints.py -q
```

Expected: current CLI requires Pinecone credentials/reference and current report validator rejects a reference-free valid execution.

- [ ] **Step 3: Implement Qdrant-only default and fail-closed gates**

The candidate queries use dense top 10 over relevant rows plus real negatives. Canary matching is document-ID based. `PASS_MODEL_PROBE` requires all absolute gates, vector readback, exact point count, and zero technical errors. A supplied static reference remains bound and reported but cannot relax an absolute gate.

- [ ] **Step 4: Run Task 3 GREEN and commit**

```powershell
python -m pytest tests/evaluation/test_structural_model_probe.py tests/evaluation/test_default_entrypoints.py tests/ingestion/test_structural_qdrant.py -q
python run_structural_index_pilot.py probe-model --help
python -m ruff check app/evaluation/structural_model_probe.py run_structural_index_pilot.py tests/evaluation/test_structural_model_probe.py tests/evaluation/test_default_entrypoints.py
git diff --check
git add app/evaluation/structural_model_probe.py run_structural_index_pilot.py tests/evaluation/test_structural_model_probe.py tests/evaluation/test_default_entrypoints.py
git commit -m "feat(eval): make structural probe Qdrant-only"
```

### Task 4: Recall≈1 final benchmark gates and reranker contribution

**Files:**
- Modify: `app/evaluation/structural_pilot_eval.py`
- Modify: `tests/evaluation/test_structural_pilot_eval.py`
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/evaluation/CURRENT_STATUS.md`

**Interfaces:**
- Changes: `decide_pilot_acceptance()` to the exact thresholds in Global Constraints.
- Produces: `reranker_contribution` with fused-input and reranker-output metric deltas on the same cases.

- [ ] **Step 1: Write failing acceptance and contribution tests**

```python
def test_pilot_pass_requires_near_one_structural_quality() -> None:
    assert decide_pilot_acceptance(report(
        document_recall_24=1.0,
        article_recall_24=0.95,
        clause_recall_24=0.90,
        all_required_coverage=0.95,
        no_candidate_rate=0.0,
        retrieval_error_rate=0.0,
        reranker_error_rate=0.0,
    )) == "PASS_PILOT"

def test_reranker_contribution_uses_same_case_denominator() -> None:
    contribution = compute_reranker_contribution(rows())
    assert contribution.document_recall_delta == (
        contribution.reranker_output.document_recall
        - contribution.reranker_input.document_recall
    )
```

Test every boundary independently, null Article/Clause denominator handling, skipped-case identity equality, and typed blocked precedence over quality failure.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_structural_pilot_eval.py -q`

Expected: the current weaker `+0.25/nonzero` acceptance passes reports that the new contract rejects.

- [ ] **Step 3: Implement exact acceptance and report fields**

Use numerators/denominators already produced by deterministic metric v3. A non-applicable Article/Clause denominator is reported null and does not become a false zero; the current verified set has nonzero denominators, so both thresholds apply to the P3 benchmark.

- [ ] **Step 4: Update source-of-truth documentation**

Record the new inference-text version, real-negative/canary probe, no-Pinecone default, exact gates, and all remote phases as `NOT RUN`. Retain P2 Recall=0 and provenance unchanged as historical evidence.

- [ ] **Step 5: Run Task 4 GREEN and commit**

```powershell
python -m pytest tests/evaluation/test_structural_pilot_eval.py tests/evaluation/test_retrieval_metrics_v3.py tests/evaluation/test_default_entrypoints.py -q
python -m ruff check app/evaluation/structural_pilot_eval.py tests/evaluation/test_structural_pilot_eval.py
git diff --check
git add app/evaluation/structural_pilot_eval.py tests/evaluation/test_structural_pilot_eval.py docs/PROJECT_CONTEXT.md docs/CURRENT_ARCHITECTURE.md docs/evaluation/CURRENT_STATUS.md
git commit -m "feat(eval): require near-perfect structural recall"
```

### Task 5: Local proof, review, and user-run handoff

**Files:**
- Modify: `docs/evaluation/CURRENT_STATUS.md` only if exact verification evidence differs from Task 4 documentation.
- Create through existing CLI: one immutable provider-free `audit` artifact and one capacity plan artifact under `docs/evaluation/index-pilots/`.

**Interfaces:**
- Consumes all prior tasks.
- Produces no remote state; produces exact local source hashes and user-run commands.

- [ ] **Step 1: Run affected suites**

```powershell
python -m pytest tests/ingestion/test_structural_index.py tests/ingestion/test_structural_qdrant.py tests/ingestion/test_structural_checkpoint.py tests/ingestion/test_structural_upload.py tests/ingestion/test_structural_pilot.py tests/evaluation/test_structural_model_probe.py tests/services/test_structural_retrieval.py tests/evaluation/test_structural_pilot_eval.py tests/evaluation/test_default_entrypoints.py -q
```

- [ ] **Step 2: Run full and static verification once at stable source**

```powershell
python -m pytest -q
python -m ruff check app/config.py app/ingestion app/evaluation app/services/structural_retrieval.py run_structural_index_pilot.py run_structural_retrieval_eval.py tests/ingestion tests/evaluation tests/services/test_structural_retrieval.py
python -m compileall -q app run_structural_index_pilot.py run_structural_retrieval_eval.py
python run_structural_index_pilot.py --help
python run_structural_retrieval_eval.py --help
git diff --check
```

Report repository-wide pre-existing lint failures separately; never relabel them as task passes.

- [ ] **Step 3: Run CRG review**

Update the graph at current HEAD, call minimal context, then detect changes with depth 2. Inspect every high-impact retrieval/ingestion flow and confirm `get_legal_retriever()` and API routes remain unchanged.

- [ ] **Step 4: Generate provider-free local artifacts**

Run `audit` and `plan` against the real local content store. Include 4 GiB disk, 1 GiB RAM, 0.5 vCPU, one shard, and observed existing disk bytes only if the user supplies current telemetry. Missing telemetry must still produce `BLOCKED_CAPACITY`, not an assumed zero.

- [ ] **Step 5: Commit final local evidence**

Stage only source-of-truth documentation and new immutable local artifacts, run `git diff --cached --check`, and commit with:

```powershell
git commit -m "docs(eval): hand off structural recall reindex"
```

- [ ] **Step 6: Hand off exact remote commands without executing them**

Populate every plan/source/upstream artifact SHA from the new immutable files. Mark `create`, `probe-model`, `upload`, `finalize`, `verify`, and `benchmark` as `NOT RUN`. State that measured Recall remains P2 `0` until the user completes those commands; do not promise a PASS before the saved benchmark exists.
