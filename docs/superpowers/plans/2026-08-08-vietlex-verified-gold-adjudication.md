# VietLex Verified Gold Adjudication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-free, immutable 40-case human adjudication queue and a fail-closed preview/promotion workflow that can create a new verified-gold sidecar only after explicit approval of an exact preview hash.

**Architecture:** Pure adjudication contracts and transformations live in `app/evaluation/adjudication.py`; read-only local corpus discovery lives in `app/evaluation/adjudication_candidates.py`; `run_gold_adjudication.py` owns CLI/path/persistence orchestration. Queue, decisions, preview, and promoted artifacts are separate immutable stages.

**Tech Stack:** Python 3.10+, Pydantic, SQLite FTS5, local Zstandard content store, pytest, CRG, Git.

## Global Constraints

- Use the design in `docs/superpowers/specs/2026-08-08-vietlex-verified-gold-adjudication-design.md`.
- Default target is exactly 40 cases; accepted CLI range is 30–50.
- Deterministic discovery never creates `verified` status.
- No provider call, Ragas, ingestion, index rebuild, corpus mutation, or persistent vector change.
- Promotion requires an exact preview hash plus explicit user approval after the preview report; current commit/merge authority is insufficient.
- Outputs are unique, repository-relative, immutable, and provenance-complete.
- Preserve negative decisions and fail closed on missing structure or identity.

---

### Task 1: Adjudication contracts and stratified selection

**Files:**
- Create: `app/evaluation/adjudication.py`
- Create: `tests/evaluation/test_gold_adjudication.py`
- Modify: `app/evaluation/schemas.py`

**Interfaces:**
- Produces: `AdjudicationDecision`, `AdjudicationCandidate`, `AdjudicationQueueRow`, `select_stratified_case_ids()`, `build_queue_payload()`, and `build_decision_template()`.
- Consumes: `GoldenCase`, `GoldEvidence`, `GitProvenance`, canonical JSON hashing.

- [ ] **Step 1: Write RED contract tests**

Add tests with these exact assertions:

```python
selected = select_stratified_case_ids(cases, labels_by_case, target_cases=40, seed="p1-v1")
assert len(selected) == 40
assert selected == select_stratified_case_ids(cases, labels_by_case, target_cases=40, seed="p1-v1")
assert {cases_by_id[item].question_type for item in selected} == {"factoid", "multi-hop"}
with pytest.raises(ValueError, match="30 and 50"):
    select_stratified_case_ids(cases, labels_by_case, target_cases=29, seed="p1-v1")
```

Assert queue rows contain full SHA-256 reference hashes, parsed citation units, empty-or-real candidates, and exactly this pending decision:

```python
{"status": "pending", "selected_candidate_id": None, "confidence": "unreviewed",
 "notes": "", "reviewer_identity": None, "reviewed_at_utc": None}
```

Assert no queue row or candidate builder can emit `status="verified"` as an automated decision.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py -q`

Expected: import failure because `app.evaluation.adjudication` does not exist.

- [ ] **Step 3: Implement strict models and selection**

Use these signatures:

```python
def canonical_sha256(data: Any) -> str: ...

def select_stratified_case_ids(
    cases: Sequence[GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    *, target_cases: int = 40, seed: str = "vietlex-p1-v1",
) -> list[str]: ...

def build_queue_payload(
    *, cases: Sequence[GoldenCase], sidecar: GoldSidecar,
    candidates_by_evidence_id: Mapping[str, Sequence[AdjudicationCandidate]],
    selected_case_ids: Sequence[str], dataset_sha256: str,
    corpus_revision: str, provenance: GitProvenance, command: Sequence[str],
    candidate_limit: int, selection_seed: str,
) -> dict[str, Any]: ...

def build_decision_template(queue_payload: Mapping[str, Any], queue_sha256: str) -> dict[str, Any]: ...
```

Extend `EvidenceStatus` with `rejected`, `corpus_missing`, and `insufficient_evidence`. Add optional adjudication provenance fields to `GoldEvidence` so promoted labels survive canonical loading.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py tests/test_evaluation_framework.py -q`

Commit: `feat(eval): add gold adjudication contracts`

### Task 2: Read-only candidate discovery

**Files:**
- Create: `app/evaluation/adjudication_candidates.py`
- Modify: `tests/evaluation/test_gold_adjudication.py`

**Interfaces:**
- Consumes: selected cases, sidecar labels, `LegalFtsIndex`, `ContentStore`, `chunk_document`, shared legal-citation/anchor logic.
- Produces: `discover_adjudication_candidates(...) -> dict[str, list[AdjudicationCandidate]]`.

- [ ] **Step 1: Write RED candidate tests**

Use a temporary title/document-number FTS and injected fake content store. Assert:

- one FTS lookup per selected case, not per evidence row;
- source-sidecar document IDs rank before FTS candidates;
- document IDs deduplicate stably;
- candidate identity includes ID/number/URL/content hash;
- article/clause values come only from a structurally matched chunk;
- unmatched candidates remain with `anchor_match_method="none"` and `required_level_supported=False`;
- no provider factory or network path is imported/called.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py -q`

Expected: missing candidate-discovery import.

- [ ] **Step 3: Implement bounded discovery**

Use this signature:

```python
def discover_adjudication_candidates(
    *, cases_by_id: Mapping[str, GoldenCase],
    labels_by_case_id: Mapping[str, Sequence[GoldEvidence]],
    selected_case_ids: Sequence[str], content_store: ContentStore,
    fts_index: LegalFtsIndex, candidate_limit: int = 12,
) -> dict[str, list[AdjudicationCandidate]]: ...
```

Build one query per case from its question and parsed document numbers. Fetch each case's documents once. Cache legal chunks by document ID during that case. Keep the existing FTS truth: exact number plus title only.

- [ ] **Step 4: Run GREEN and focused integration tests**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py tests/evaluation/test_legal_citations.py tests/ingestion/test_legal_fts.py tests/ingestion/test_legal_text.py -q`

- [ ] **Step 5: Commit**

Commit: `feat(eval): discover adjudication candidates locally`

### Task 3: Decision validation and promotion preview

**Files:**
- Modify: `app/evaluation/adjudication.py`
- Modify: `tests/evaluation/test_gold_adjudication.py`

**Interfaces:**
- Produces: `validate_decisions()` and `build_promotion_preview()`.
- Consumes: queue payload/file hash, decision artifact, raw source sidecar, exact dataset case IDs.

- [ ] **Step 1: Write RED decision tests**

Assert failures for queue hash mismatch, missing/extra row, `pending`, naive timestamp, empty reviewer, missing negative notes, unknown candidate, verified candidate without document anchor, and missing required Article/Clause structure.

Assert all negative decisions remain in preview status counts and map to explicit non-verified sidecar statuses. Assert verified rows copy candidate identity/locators, never reviewer hints.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py -q`

- [ ] **Step 3: Implement validation and pure preview**

Use these signatures:

```python
def validate_decisions(
    queue_payload: Mapping[str, Any], decisions_payload: Mapping[str, Any],
    *, queue_sha256: str,
) -> list[AdjudicationDecision]: ...

def build_promotion_preview(
    *, queue_payload: Mapping[str, Any], queue_sha256: str,
    decisions_payload: Mapping[str, Any], source_sidecar_payload: Mapping[str, Any],
    source_sidecar_sha256: str, dataset_case_ids: Sequence[str],
    provenance: GitProvenance,
) -> dict[str, Any]: ...
```

The preview embeds the complete proposed sidecar, a compact per-evidence diff, before/after status counts, verified case count, negative decision counts, exact case-set result, source hashes, and `preview_sha256` computed over the preview core.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py tests/evaluation/test_runtime_contracts.py -q`

Commit: `feat(eval): validate human gold decisions`

### Task 4: Explicitly approved immutable promotion

**Files:**
- Modify: `app/evaluation/adjudication.py`
- Modify: `tests/evaluation/test_gold_adjudication.py`

**Interfaces:**
- Produces: `validate_preview_approval()` and `build_promotion_summary()`; persistence remains in the CLI.

- [ ] **Step 1: Write RED approval tests**

Assert missing/wrong preview hash fails before any file write. Assert exact approval produces a sidecar payload that reloads with `load_gold_sidecar(..., dataset_case_ids=...)`. Assert output collision never overwrites bytes.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py -q`

- [ ] **Step 3: Implement exact approval gate**

```python
def validate_preview_approval(
    preview_payload: Mapping[str, Any], approved_preview_sha256: str,
) -> None: ...

def build_promotion_summary(preview_payload: Mapping[str, Any]) -> dict[str, Any]: ...
```

Require equality with `preview_payload["preview_sha256"]`; reject empty approval. The promoted sidecar keeps schema `2.0.0`, unchanged case/evidence counts, reviewer/time/confidence provenance, notes hash, queue SHA, and selected candidate ID.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py tests/evaluation/test_provenance.py tests/evaluation/test_preflight.py -q`

Commit: `feat(eval): gate immutable gold promotion`

### Task 5: Provider-free CLI orchestration

**Files:**
- Create: `run_gold_adjudication.py`
- Modify: `tests/evaluation/test_gold_adjudication.py`
- Modify: `README.md`

**Interfaces:**
- Produces CLI subcommands `queue`, `preview`, and `promote`.
- Consumes the pure functions from Tasks 1–4 and `write_immutable_json()`/`prepare_run_directory()`.

- [ ] **Step 1: Write RED CLI tests**

Assert `--help` does not open corpus/provider clients. Run `queue` against temporary dataset/sidecar/fake corpus and assert three immutable JSON files, portable paths, provider calls `0`, and pending-only decisions. Assert output roots outside the repository fail before persistence.

Run `preview` with resolved decisions and assert it writes only `preview.json`. Run `promote` without approval and assert no sidecar directory/file is created.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py -q`

- [ ] **Step 3: Implement argparse and IO**

Required commands:

```powershell
python -u run_gold_adjudication.py queue --dataset <path> --sidecar <path> --content-store <path> --fts <path> --target-cases 40 --candidate-limit 12
python -u run_gold_adjudication.py preview --dataset <path> --sidecar <path> --queue <queue.json> --decisions <decisions.json>
python -u run_gold_adjudication.py promote --dataset <path> --sidecar <path> --queue <queue.json> --decisions <decisions.json> --preview <preview.json> --approve-preview-sha256 <approved-hash>
```

All defaults are repository-local and provider-free. Promotion uses a new run directory and never edits `--sidecar`.

- [ ] **Step 4: Run GREEN and entrypoint checks**

Run: `python -m pytest tests/evaluation/test_gold_adjudication.py tests/evaluation/test_default_entrypoints.py -q`

- [ ] **Step 5: Commit**

Commit: `feat(eval): add gold adjudication CLI`

### Task 6: Review, stable-tree verification, and real clean queue

**Files:**
- Modify: `docs/evaluation/CURRENT_STATUS.md`
- Create after clean tooling commit: `docs/evaluation/adjudication/queues/<queue-id>/queue.json`
- Create after clean tooling commit: `docs/evaluation/adjudication/queues/<queue-id>/decision_template.json`
- Create after clean tooling commit: `docs/evaluation/adjudication/queues/<queue-id>/queue_summary.json`

**Interfaces:**
- Consumes: pinned dataset at the user checkout, read-only content store/FTS, clean P1 tooling commit.
- Produces: a durable human-review queue and honest P1 blocker status.

- [ ] **Step 1: CRG and independent review**

Update the graph after source stabilizes, run `detect_changes_tool` minimal, validate findings against source, and obtain one independent Critical/Important review. Fix through RED/GREEN cycles.

- [ ] **Step 2: Verify stable source once**

Run:

```powershell
python -m pytest -q tests/evaluation/test_gold_adjudication.py tests/evaluation/test_legal_citations.py tests/evaluation/test_provenance.py tests/evaluation/test_preflight.py tests/evaluation/test_runtime_contracts.py
python -m pytest -q tests/test_evaluation_framework.py tests/test_run_eval_suite.py tests/ingestion/test_legal_fts.py tests/ingestion/test_legal_text.py
python -m pytest -q
python -m ruff check --select E4,E7,E9,F app/ run_gold_adjudication.py tests/evaluation/test_gold_adjudication.py
python -m compileall -q app tests run_gold_adjudication.py
git diff --check
```

- [ ] **Step 3: Commit tooling and merge locally**

Stage explicit P1 source/test/doc paths, commit, and merge to local `main`; do not push.

- [ ] **Step 4: Generate the real queue from a clean commit**

Use explicit absolute paths for the ignored dataset/content store/FTS. Require `target_cases=40`, `candidate_limit=12`, `provider_calls=0`, exact sidecar case set, and clean Git provenance. If generation completes with 30–50 cases, preserve the queue artifacts; otherwise preserve a `BLOCKED` artifact.

- [ ] **Step 5: Validate and commit queue evidence**

Reload every JSON file, verify hashes/path portability, confirm all decisions remain `pending`, update `CURRENT_STATUS.md`, commit locally on `main`, and stop before preview/promotion.

## Self-Review

- Spec coverage: immutable queue, 30–50 stratification, required row fields, negative decisions, human-only verification, preview/report, versioned sidecar, exact case set, provenance, and no-provider constraints all map to tasks.
- Placeholder scan: no deferred code step, `TBD`, or `TODO` remains.
- Type consistency: function names/signatures and artifact names are stable across Tasks 1–6.
- Boundary check: P2 and evidence promotion remain blocked until human decisions plus explicit preview approval exist.
