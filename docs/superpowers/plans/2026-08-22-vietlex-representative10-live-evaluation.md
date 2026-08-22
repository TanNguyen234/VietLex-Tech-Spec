# VietLex Representative-10 Live Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commit the reviewed remediation in coherent units, then run one immutable live evaluation over the ten pinned Representative-10 cases using deterministic code metrics, NeMo guardrails, and opt-in Ragas.

**Architecture:** Keep the canonical V5 manifest as the evaluation identity boundary. Use `run_answer_eval.py` once with explicit case IDs, guardrails in enforce mode, Ragas enabled, concurrency one, and a unique run ID; inspect immutable artifacts and stop after reporting results rather than tuning the system in the same evidence cycle.

**Tech Stack:** Git, Python 3.10+, pytest, VietLex evaluation v2, NeMo Guardrails, Ragas, Pinecone/Qdrant retrieval, Vertex AI generation/judge.

**Spec:** `docs/evaluation/current_evaluation.json`

## Global Constraints

- Dataset: `app/data/namsyntax_legal_qa_420_curated_v1.json`, SHA-256 `b458880e2c2fc4f2813965d57dc96517555488a5ada3702da12fb811f05fb90b`.
- Gold sidecar: curated V5, SHA-256 `f6dfe09a6f32697b468d43c36bd9fd82d5fe5c0c4b0e5d9684ca3e4d0c1f5b67`.
- Cases, in order: `case_017 case_036 case_061 case_101 case_165 case_243 case_261 case_323 case_329 case_397`.
- No gold promotion, ingestion, reindexing, migration, deletion, push, or PR.
- A provider/configuration failure is a technical error, never a quality score.
- Preserve existing untracked evaluation artifacts and record the dirty-tree provenance honestly.

---

### Task 1: Split the reviewed remediation into coherent commits

**Files:**
- Modify: `.codex/config.toml`
- Modify: `run_retrieval_eval.py`, `run_answer_eval.py`, `run_eval_suite.py`
- Create: `docs/evaluation/current_evaluation.json`
- Modify: `tests/evaluation/test_default_entrypoints.py`
- Modify: `app/api/routes.py`, `tests/test_api_routes.py`
- Modify: `requirements.txt`, `.env.example`, `README.md`
- Create: `docs/superpowers/plans/2026-08-22-vietlex-lean-remediation.md`

**Interfaces:**
- Consumes: reviewed working-tree diff against `3fadec1`.
- Produces: four independently named local commits; the execution plan travels with the setup/documentation commit.

- [ ] **Step 1: Verify the stable combined source**

Run:

```powershell
python -m pytest -q
git diff --check
```

Expected: suite exits zero; only documented skips/deprecation warnings; no whitespace error.

- [ ] **Step 2: Commit Codex project configuration**

```powershell
git add -- .codex/config.toml
git commit -m "fix(codex): remove invalid project skill paths"
```

- [ ] **Step 3: Commit canonical evaluation defaults**

```powershell
git add -- run_retrieval_eval.py run_answer_eval.py run_eval_suite.py tests/evaluation/test_default_entrypoints.py docs/evaluation/current_evaluation.json docs/superpowers/plans/2026-08-22-vietlex-lean-remediation.md
git commit -m "fix(evaluation): pin curated v5 default contract"
```

- [ ] **Step 4: Commit guardrail/cache ordering**

```powershell
git add -- app/api/routes.py tests/test_api_routes.py
git commit -m "fix(safety): guard input before semantic cache"
```

- [ ] **Step 5: Commit local setup contract and execution plan**

```powershell
git add -- requirements.txt .env.example README.md docs/superpowers/plans/2026-08-22-vietlex-representative10-live-evaluation.md
git commit -m "docs(setup): document mongodb runtime contract"
```

### Task 2: Provider-free preflight

**Files:**
- Read: `.env`, `app/config.py`, canonical dataset/sidecar, ContentStore/FTS paths

**Interfaces:**
- Consumes: committed source and local provider configuration.
- Produces: boolean-only readiness evidence without printing secrets.

- [ ] **Step 1: Confirm exact identities and local dependencies**

Run a bounded Python probe that verifies both manifest hashes, ten unique selected case IDs, ContentStore/FTS presence, and configured provider credentials while printing only booleans and provider/model identifiers.

- [ ] **Step 2: Stop on missing prerequisites**

Do not invoke a paid provider when canonical identities, local retrieval stores, or primary credentials are absent. Report the exact missing class without exposing values.

### Task 3: Run the immutable live evaluation once

**Files:**
- Create: `docs/evaluation/runs/answer-representative10-v5-live-20260822/`

**Interfaces:**
- Consumes: canonical V5 contract and the ten explicit case IDs.
- Produces: manifest, configuration, selected-case set, retrieval results, answer results, and report.

- [ ] **Step 1: Execute the live run**

```powershell
python -u run_answer_eval.py --case-ids case_017 case_036 case_061 case_101 case_165 case_243 case_261 case_323 case_329 case_397 --verified-only --gold-policy all-required-verified --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --judge ragas --run-id answer-representative10-v5-live-20260822
```

Expected: exactly ten selected cases and a unique immutable run directory. Any technical/provider error remains visible in per-case status and is not retried by changing code during this run.

### Task 4: Inspect and report without tuning

**Files:**
- Read: `docs/evaluation/runs/answer-representative10-v5-live-20260822/*.json`
- Create: user-facing summary in the Codex task `outputs/` directory

**Interfaces:**
- Consumes: exact immutable run artifacts.
- Produces: metric table, per-case failure analysis, provider/guardrail/Ragas execution coverage, latency summary, and next-step recommendation.

- [ ] **Step 1: Validate artifact completeness**

Check selected count/order/hash, dataset/sidecar hashes, Git dirty proof, provider observations, ten per-case results, guardrail statuses, deterministic metric denominators, Ragas coverage/errors, and report hash.

- [ ] **Step 2: Classify the outcome**

Separate retrieval misses, generation errors, guardrail false positives/technical failures, Ragas technical failures, and low deterministic scores. Do not average technical failures into quality scores.

- [ ] **Step 3: Stop after evidence-backed recommendation**

Do not modify retrieval, models, prompts, guardrails, gold labels, or provider policy in the same run. Present the smallest next experiment based on the dominant observed failure class.
