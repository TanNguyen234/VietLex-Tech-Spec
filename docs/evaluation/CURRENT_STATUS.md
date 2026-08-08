# VietLex Evaluation Current Status

**Status:** P0 and lean workflow verified locally; clean committed baseline NOT RUN

- Historical 2026-08-03 retrieval runs remain invalid for decision-making.
- Current sidecar: 420 cases, 483 evidence items, 0 verified evidence items.
- Clean live retrieval baseline: **BLOCKED** until verified gold exists and P0 is committed/clean.
- Ragas: optional audit only; disabled by default.
- Production readiness: **NOT DEMONSTRATED**.

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

## Provider-free P0 preflight

- Artifact: `docs/evaluation/preflight/p0-final-a4a93aded267483bb3bf54a89c723275/`.
- Expected process exit: 1 (`BLOCKED`).
- Profiles: 3 (`legacy`, `separated_no_intent`, `separated_intent`).
- Selected cases: 0 under `all-required-verified` and `verified-only`.
- Provider calls: 0.
- Source-state SHA-256 at P0 preflight: `0f60228d92ea45f2da2e5bccdd351e9418f8f7c2d4662c733583b43646ecfc8a`.
- Selected-case-set SHA-256: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- All canonical artifact paths are repository-relative POSIX paths.

Remote data modified: **no**. Live benchmark, live provider evaluation, ingestion, migration, deployment, commit, and push: **NOT RUN**.

The latest verified source-state SHA-256 after adding the project-local lean workflow is `3eb7e2a71b91431b1a3d04f14e8010037c75712ddec1c6edfa9e252621995c05`. A matching clean provider-free preflight remains **NOT RUN** until after the source commit.
