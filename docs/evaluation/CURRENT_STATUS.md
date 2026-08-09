# VietLex Evaluation Current Status

**Status:** P1 anchor-backed provider-free adjudication queue READY_FOR_REVIEW; human decisions pending; live baseline BLOCKED by zero verified gold

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
- Real queue generation: **COMPLETED provider-free** on 2026-08-09; details are pinned below.
- Human decisions, promotion preview, preview approval, evidence promotion, provider calls, corpus/index mutation, and P2: **NOT RUN**.

Anchor-candidate discovery was verified on 2026-08-09 and committed as `7b8347a2bf1e956110446292c0c62959b4acd5c1`.

- Source-document fallback scans the local content store read-only by bounded normative legal-type tiers and reuses the deterministic normalized-anchor matcher.
- Source-sidecar IDs remain first, anchor matches rank before title/document-number FTS noise, and scan absence is explicitly not treated as proof that a source is missing from the corpus.
- Focused suite: `158 passed in 59.92s`; broader relevant suite: `233 passed in 70.43s`; full suite: `375 passed, 1 skipped in 80.65s`.
- Ruff fatal checks, compileall, `git diff --check`, and compact CRG review passed; CRG risk score was low (`0.40`).

Resume with human review of the immutable decision template. Do not run promotion unless the user explicitly approves the exact future preview SHA-256.

## P1 current anchor-backed adjudication queue

- Artifact: `docs/evaluation/adjudication/queues/gold-adjudication-queue_20260809_140617_989731_00000000/`.
- Queue status: `READY_FOR_REVIEW`; selected cases: 40/40 from 245 eligible cases; selection shortfall: 0.
- Selected strata: `factoid|article=7`, `factoid|clause=7`, `factoid|document=7`, `multi-hop|article=7`, `multi-hop|clause=6`, `multi-hop|document=6`.
- Review rows: 52; candidates: 624 (12 per row); zero-candidate rows: 0.
- Anchor scan candidates: 71. The exact source laws `72/2020/QH14` and `59/2020/QH14` are surfaced for all 52 evidence rows (24 and 28 rows respectively).
- Structural gate: 38 supported candidates across 32/52 evidence rows; 20 rows remain unsupported because the supplied Article/Clause requirement conflicts with the matched source structure. Only 22/40 cases currently have supported candidates for every queued evidence row.
- Decision template: 52/52 decisions remain `pending`; selected candidates: 0; reviewer identities: 0; no raw `adjudication_notes` key is persisted.
- Dataset SHA-256: `84c93a522c1bc8eac7179aa808f70b59466fe9a55a4a9f98ddae07797c9662c7`.
- Source sidecar SHA-256: `c63932ac4101a37ab189d665ea181c4672faac8e9de035d0d83797384d5aa18a`.
- Queue SHA-256: `a2fab7aa14813d5f621db31aa3b09213621ad1469d169614558613c27bae9db8`.
- Decision-template SHA-256: `3ac328220e5843fc450f001fcd8970f6711560439351429130130d1936a727af`.
- Queue-summary SHA-256: `41a700e5ac87e9da6492eb84fd990d56059a0375b93ddb1f93540545b54f52e9`.
- Source Git SHA: `7b8347a2bf1e956110446292c0c62959b4acd5c1` with `git_dirty=true` only because two pre-existing preflight artifact directories were untracked; tracked and staged state were clean. Git diff SHA-256: `5b4523cbbaca0523daf8681093e7a9772ae7eed42437547ae176dc82c5e29121`; source-state SHA-256: `1b8c338a34bbc74345ded3c48ff0257ea1dc79ffe0b4ad032680fa02f8cfbb3b`.
- The local content store and FTS were opened read-only. Provider calls: 0. Remote data modified: no.

Exact generation command:

```powershell
python -u run_gold_adjudication.py queue --dataset D:\Download\ProfessionalLegalRAG\app\data\namsyntax_legal_qa_420.json --sidecar D:\Download\ProfessionalLegalRAG\docs\evaluation\gold_labels\namsyntax_legal_qa_420_labels_v2.json --content-store D:\Download\ProfessionalLegalRAG\data\huggingface\content_store.sqlite3 --fts D:\Download\ProfessionalLegalRAG\data\huggingface\legal_fts.sqlite3 --output-root D:\Download\ProfessionalLegalRAG\docs\evaluation\adjudication\queues --target-cases 40 --candidate-limit 12
```

Generation exited 0 in 124.5 seconds. JSON reload and canonical SHA-256 validation confirmed all counts and artifact hashes above. The prior FTS-only queue remains immutable: queue SHA-256 `680a144c928f7b32cf3268e3d2e0002a4c98c4172a12f78508d5013e5e3e32e0`, decision-template SHA-256 `69c5af91844f4c38c81a014c1ad4777da6ff6137ba3c37b0fa64019ee7c38c3b`.

Human adjudication is still required. No candidate was automatically accepted, no preview was created, and no evidence was promoted. P2 remains blocked until at least 30 cases satisfy the verified-gold gate.

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
- Lean Superpowers v2 sets automatic worktree creation OFF, routes repository work through CRG with source validation, and delays broad/full verification until final review is clean. Five no-guidance controls scored 10/30 protocol controls versus 28/30 with the skill; no numeric token-reduction percentage is claimed because token counters were unavailable.

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
