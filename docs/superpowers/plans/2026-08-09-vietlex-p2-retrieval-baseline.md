# VietLex P2 Verified Retrieval Baseline Plan

> **Execution mode:** VietLex Lean Superpowers; worktree creation OFF. Execute on local `main` in isolated, reviewable commits. No ingestion, index mutation, generation, Ragas, or guardrail calls.

**Goal:** Produce the first reproducible retrieval-only comparison for `legacy`, `separated_no_intent`, and `separated_intent` using the same 40 `all-required-verified` cases, promoted gold sidecar, provider configuration, corpus revision, evaluation code, and clean Git SHA.

**Inputs pinned before live calls**

- Dataset: `app/data/namsyntax_legal_qa_420_curated_v1.json`; SHA-256 `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`.
- Promoted sidecar: `docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json`; file SHA-256 `6044c084fd0cfd7b696b7e927ae2df26130e090aa64cf1a3b39a0784c1d8a9bf`.
- Approved preview SHA-256: `89138b35c77998c03d797d92c6e9d9a31070abc02bf4becb1a0fb26dbea5387c`.
- Gold policy: `all-required-verified`; `verified-only=true`; expected selected cases: 40.
- Query rewrite: `off`; reranker mode: `current`; concurrency: 1.

## Task 1: Remove the unrelated-summary preflight blocker

**Files:** `run_retrieval_eval.py`, `tests/evaluation/test_preflight.py`, `tests/evaluation/test_default_entrypoints.py`.

1. Add a failing test proving an explicitly supplied promoted sidecar does not inherit the legacy v2 audit summary.
2. Add a failing test proving an explicitly supplied audit summary is still validated fail-closed.
3. Implement the smallest CLI/path-resolution change: legacy default sidecar may use its matching default summary; a custom sidecar uses no implicit unrelated summary; `--audit-summary` opts into a specific summary.
4. Run focused tests, fatal Ruff checks, compileall, and diff check.

## Task 2: Create a clean, reproducible P1/P2 source checkpoint

1. Update `docs/evaluation/CURRENT_STATUS.md` with the exact promoted artifact, hashes, 53 verified evidence items, 40 fully verified cases, and fresh test evidence.
2. Preserve the two pre-existing untracked P0 directories unchanged and exclude only those exact local paths from Git cleanliness checks.
3. Track the curated dataset despite the general raw-data ignore because its bytes are a required P2 benchmark input; stage only the reviewed P1/P2 artifacts, code, tests, plan, and status.
4. Review staged diff, verify artifact JSON reload/hashes and absence of raw notes, then create a local checkpoint commit.

## Task 3: Run official provider-free all-profile preflight

1. From the clean checkpoint, execute `run_retrieval_eval.py --preflight-all-profiles --verified-only --gold-policy all-required-verified --require-clean-git` with the pinned dataset and promoted sidecar.
2. Require: exit 0, `READY`, provider calls 0, 40 identical selected case IDs for all three profiles, identical dataset/sidecar/source-state hashes, clean Git provenance.
3. Reload every emitted JSON and recompute hashes. Commit the immutable preflight evidence so the live benchmark again starts clean.

## Task 4: Execute the three live retrieval profiles on one source state

1. Predeclare unique run IDs and locally exclude only those exact output directories while the three sequential runs execute. This prevents the first immutable artifact from making the second run appear source-dirty without hiding any source or input change.
2. Run `legacy`, `separated_no_intent`, and `separated_intent` with the pinned inputs and flags above, `--require-clean-git`, and no `--limit`.
3. Stop the batch if any manifest differs in Git SHA, source-state SHA, dataset SHA, sidecar SHA, selected-case-set SHA, rewrite/reranker mode, corpus revision, configured provider identifiers, or evaluation metric version.
4. Preserve technical failures as typed run results; do not rerun only failed cases or replace results.

## Task 5: Build and verify the comparison

1. Load the three immutable manifests/results and validate exact input/source equality before comparing metrics.
2. Report per profile: document recall by K and stage, Article/Clause recall, MRR, nDCG@10, exact-reference hit, multi-hop coverage, first-loss counts, no-candidate/retrieval/reranker error rates, reranker-stage contribution, and latency p50/p95/mean.
3. Include numerator, denominator, coverage, skipped cases, skip reasons, status counts, run IDs, commands, provider identifiers, and artifact SHA-256 values.
4. State limitations explicitly: configured provider identifiers do not prove which fallback answered unless runtime diagnostics record it; 40 curated verified cases are not the full 420-case dataset or the 518,255-document corpus.

## Task 6: Final review and checkpoint

1. Source-review all code changes and artifact validators; use CRG for impact radius when its graph matches the current SHA and source-validate regardless.
2. Run focused tests, the five-file evaluation suite, fatal Ruff, compileall, diff check, then full `pytest -q` once the review is clean.
3. Update `CURRENT_STATUS.md` with actual commands/results only. Mark live provider calls and remote-data mutation separately; retrieval calls are read-only and no corpus/index mutation is permitted.
4. Create a local P2 checkpoint commit. Do not push, merge remote, ingest, migrate, or delete data in this plan.
