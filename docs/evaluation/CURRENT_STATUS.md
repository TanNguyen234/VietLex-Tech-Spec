# VietLex Evaluation Current Status

**Status:** P1 provider-free adjudication tooling verified and merged; human queue generation paused; live baseline BLOCKED by zero verified gold

- Historical 2026-08-03 retrieval runs remain invalid for decision-making.
- Current sidecar: 420 cases, 483 evidence items, 0 verified evidence items.
- Clean live retrieval baseline: **BLOCKED** until verified gold exists and P0 is committed/clean.
- Ragas: optional audit only; disabled by default.
- Production readiness: **NOT DEMONSTRATED**.

## P1 adjudication tooling checkpoint

Verified on 2026-08-08 from feature source SHA `2f08c5283c233ed108b5ab5de5010dbc5e7e598f`, merged locally as `70597c45c9e265bdb31c9d6756d2e2ff12204b79`.

- Added immutable provider-free `queue`, `preview`, and explicitly approved `promote` workflows.
- Pinned legacy 16-character anchor hashes are preserved separately; full anchor SHA-256 values bind the exact indexed reference context.
- Queue and decision bindings use exact immutable artifact bytes. Candidate IDs bind document identity and content hashes.
- Selection round-robins `(question_type, highest_required_level)` strata and persists an honest BLOCKED queue when fewer than 30 cases are eligible.
- Mandatory post-fix suite: `191 passed`.
- Stable full suite: `362 passed, 1 skipped in 45.67s`.
- Ruff fatal checks, compileall, and `git diff --check`: passed.
- CRG graph matched the final feature SHA; independent final review reported no remaining actionable finding and `Ready to merge: Yes`.
- Real queue generation, human decisions, preview approval, evidence promotion, provider calls, corpus/index mutation, and P2: **NOT RUN**.

Resume with the documented `run_gold_adjudication.py queue` command using the pinned dataset/content-store/FTS paths. Stop again before promotion unless the user explicitly approves the exact preview SHA-256.

## Evidence policy

Only immutable runs with dataset, sidecar, source-state, configuration, provider/model, command, and metric-version provenance may be used for decisions.

## Verification evidence

Verified on 2026-08-08 from Git SHA `4e40be6ab1871e3b64ca6f560f317bed215e05e1` with `git_dirty=true`.

- `python -m pytest -q tests/skills/test_vietlex_lean_superpowers.py tests/evaluation/test_runtime_contracts.py tests/evaluation/test_provenance.py tests/evaluation/test_preflight.py tests/evaluation/test_legal_citations.py tests/evaluation/test_retrieval_metrics_v3.py tests/evaluation/test_reporting_v3.py tests/evaluation/test_default_entrypoints.py` — `75 passed in 27.02s`.
- `python -m pytest -q tests/test_evaluation_framework.py tests/test_run_eval_suite.py tests/test_rag_pipeline.py tests/services/test_retrieval.py tests/services/test_remote_reranker.py` — `65 passed in 17.83s`.
- `python -m pytest tests/skills/test_vietlex_lean_superpowers.py -q` — final review regressions `5 passed in 0.12s`.
- `python -m pytest -q` — `219 passed, 1 skipped in 79.51s`; the skipped test is the existing opt-in live integration test.
- `python -m ruff check --select E4,E7,E9,F app/` — `All checks passed!`.
- Extended Ruff gate over all modified P0 scripts and tests — `All checks passed!`.
- `python -m compileall -q app tests` — exit 0.
- `git diff --check` — exit 0; only Git line-ending conversion warnings were emitted.
- CI contract search confirmed Python 3.10, fatal Ruff checks, and provider-free `pytest -q` remain configured.
- Historical-run checksum preservation — `1 passed in 7.80s`; no existing path under `docs/evaluation/runs/` changed.
- CRG incremental review, independent code review, and focused re-review found no remaining Critical or Important issue.
- Lean-skill pressure tests preserved all critical quality/authority gates while removing an unnecessary implementation worktree and adding explicit query/rerun caps.

## Provider-free clean P0 preflight

- Artifact: `docs/evaluation/preflight/p0-clean-efb0bf0951f44d849ce710627e0f1afc/`.
- Expected process exit: 1 (`BLOCKED`).
- Profiles: 3 (`legacy`, `separated_no_intent`, `separated_intent`).
- Selected cases: 0 under `all-required-verified` and `verified-only`.
- Provider calls: 0.
- Git SHA: `bbd68c7dc10d6059e78ce202c606b7951694b3ad` with `git_dirty=false`.
- Source-state SHA-256: `5baba1eaa4d85bc229d888b99629a5a6ffc20160460d2e490b43acb490934d21`.
- Selected-case-set SHA-256: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- All canonical artifact paths are repository-relative POSIX paths.

Remote data modified: **no**. P0 source commit and local `main` merge: **COMPLETED**. Live benchmark, live provider evaluation, ingestion, migration, and deployment: **NOT RUN**.

The merged-result full suite passed `219 passed, 1 skipped in 73.36s`. The clean provider-free preflight matches the source state above; P1 may build adjudication tooling, but human evidence promotion remains required.
