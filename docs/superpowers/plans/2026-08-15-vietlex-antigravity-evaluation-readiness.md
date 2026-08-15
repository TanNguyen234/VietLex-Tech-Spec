# VietLex Evaluation Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `vietlex-lean-superpowers`; work task-by-task in the existing worktree. Git worktrees remain OFF.

**Goal:** Make evaluation useful for both verified golden cases and unlabeled real-user traffic, while closing P3 honestly without weakening legal-quality gates.

**Architecture:** Keep deterministic golden evaluation as the release gate. Add a separate no-gold online lane for operational metrics and optional sampled Ragas; never present online proxy scores as legal correctness. Archive the incomplete P3 attempt and preserve its checkpoint/namespace as non-production evidence.

**Tech Stack:** FastAPI, Pydantic, pytest, MongoDB logging, deterministic evaluation v3, optional Ragas.

## Global Constraints

- Default execution makes zero paid/live-provider calls; Ragas must be opt-in.
- Do not delete/recreate indexes, namespaces, checkpoints, or local stores.
- Do not stage `.codex/config.toml`; production retrieval stays unchanged until all gates pass.
- Human-only evidence promotion remains human-only. Antigravity may generate queues and previews, never self-promote labels.
- Use TDD, review the stable diff once, then run the full suite once.

---

### Task 1: Control online Ragas and add no-gold observability

**Files:** Modify `app/config.py`, `app/api/routes.py`, `app/services/evaluator.py`, `app/database.py`; create `app/evaluation/online_metrics.py`, `tests/evaluation/test_online_metrics.py`, and focused route/evaluator tests.

**Contract:** Add `RAGAS_EVALUATION_MODE=off|sample|all` with default `off` and deterministic trace-ID sampling. For every successful request, persist only observable no-gold facts: latency, status, context/citation counts, no-evidence/refusal category, technical errors, and provider usage. Label Ragas fields explicitly as proxy metrics.

- [ ] RED: prove default mode schedules zero Ragas/provider calls and online metrics never claim recall, correctness, or valid citation.
- [ ] GREEN: implement the smallest config/sampling/metric boundary; Ragas failure must be typed/logged and must not alter the answer.
- [ ] Verify: `python -m pytest tests/evaluation/test_online_metrics.py -q` plus focused API/evaluator tests; run Ruff on changed files.

### Task 2: Expand verified-gold coverage without document patching

**Files:** Reuse `run_gold_adjudication.py`, `app/evaluation/adjudication_candidates.py`, and immutable `docs/evaluation/adjudication/` outputs. Change code only if a focused RED exposes a corpus-wide defect.

**Contract:** Build provider-free review queues in deterministic 20-case batches from currently unverified cases. Report legal type, document diversity, required evidence level, candidate source/hash, and unresolved reason. Do not optimize for the existing two gold documents.

- [ ] Generate the first immutable queue and audit its hashes/counts; provider calls must equal zero.
- [ ] Produce a decision preview for user/legal review; do not promote automatically.
- [ ] After approved decisions, promote a new sidecar version and require increasing distinct-document coverage before using it as a release gate.

### Task 3: Close and archive P3

**Files:** Existing plan `docs/superpowers/plans/2026-08-14-vietlex-p3-pinecone-structural-replacement.md`; checkpoint `.superpowers/runtime/pinecone-structural-primary-20260814.sqlite3`.

**Contract:** Record `BLOCKED_EXTERNAL_QUOTA` at `21,696/134,334` uploaded chunks. The partial namespace covers 247/827 selected documents and 24/64 canary documents; it is not quality evidence and must not be benchmarked or promoted.

- [ ] Preserve the checkpoint and isolated namespace; do not resume, delete, verify, or create a synthetic upload report.
- [ ] Record upload/verify/canary/benchmark as incomplete or `NOT RUN`; remove every P3 monitor.
- [ ] Any future replacement retrieval experiment requires a new plan and the same unchanged quality gates.

### Task 4: Production-light decision package

**Files:** Update `docs/evaluation/CURRENT_STATUS.md`; create one immutable comparison/run directory only after source is stable.

- [ ] Report offline gold quality, online proxy/operational metrics, dataset/document coverage, answer/citation/refusal evaluation, latency, failures, Git provenance, and provider effects separately.
- [ ] Record `NOT PRODUCTION READY` because P3 closed before upload verification/canary/benchmark. A future retrieval experiment must independently authorize any closed alpha.
- [ ] Final gates: focused tests, stable-diff review, `python -m pytest -q`, Ruff, `git diff --check`, then one scoped commit/push excluding `.codex/config.toml`.
