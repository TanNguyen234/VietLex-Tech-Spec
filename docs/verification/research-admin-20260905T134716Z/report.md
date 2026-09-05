# Research workspace / admin evaluation verification

Delivered locally: authenticated `/admin/evaluations`, answer/retrieval run selection,
stored quality gate, status distribution, deterministic and secondary judge metrics,
coverage/skips, all recorded recall cutoffs, stage survival, latency means and case evidence.
The public Evaluation Lab stays pinned. The homepage launches existing research workflows;
light theme, self-hosted Be Vietnam Pro and exact-preserving document outlines improve reading.

This is the product-presentation/admin phase of the supplied research. Official-web search,
deep research, uploads/contract analysis, new claim verification and legal-effect relationships
are NOT IMPLEMENTED by this change. Existing retrieval, model selection and persistent stores
are unchanged. No production-readiness or improved legal-accuracy claim is made.

## Verification

- `.venv/Scripts/python.exe -m pytest -q`: **1006 passed, 2 skipped, 12 warnings**, exit 0.
  Exact output: `pytest.log`; run timestamps, Git proof and source hashes: `verification.json`.
  An earlier attempt was interrupted at approximately 28% and had no final result; it is not
  counted as passing evidence. The completed repeat used the same reviewed source.
- `.venv/Scripts/python.exe -m pytest tests/services/test_evaluation_lab.py tests/test_evaluation_lab_routes.py tests/test_legal_routes.py -q`: 22 passed after review fixes.
- `.venv/Scripts/python.exe -m pytest tests/test_evaluation_lab_routes.py -q`: 3 passed after the last template correction.
- `.venv/Scripts/python.exe -m ruff check app/services/evaluation_lab.py app/api/evaluation_lab_routes.py app/api/legal_routes.py tests/services/test_evaluation_lab.py tests/test_evaluation_lab_routes.py tests/test_legal_routes.py`: passed.
- `git diff --check`: passed (Git emitted Windows line-ending conversion notices).
- RED failures were observed before implementation for retrieval artifacts, missing metric
  coverage/truncation, all recall cutoffs/stages, authenticated run selection, outline escaping,
  malformed gate failures, current provenance fields and filesystem catalog failures.
- Independent OCR delegation review: 19/19 scoped files reviewed; three medium findings fixed
  and source-validated. Commands: `ocr delegate preview --format json`, then
  `ocr delegate rule --format json` with the 13 changed source/test paths listed below.
  CRG unavailable; source and rg fallback used. One reviewer test command had an incorrect node
  name and failed collection; its corrected regression command passed (6 tests).
- Browser smoke used a temporary localhost presentation app with a test-only admin override,
  real local artifacts and no production database. Desktop and 390px layout inspected;
  run selection and case drilldown observed. After full tests, final render confirmed the stored
  failed gate, 24/50 ok and 26/50 retrieval_error, metric version 3.0.0 and configured provider models.
  This is not live account-login, retrieval or deployed-site verification.
- Local artifact inventory: 57 selectable runs, 50 available, 6 rejected above 32 MiB,
  1 rejected for read/schema error. An initial render sweep returned no template exceptions.
  The pinned answer artifact exposes 38 deterministic aggregate rows and 110 stage rows.

## Limits and authority

Dashboard summaries cover at most 100 cases; truncation is labeled. Macro means use observed
finite values and display denominator/coverage/skip reasons. N/A is not zero. Stored gates
can have a different scope than a truncated view. Provenance is displayed, not re-certified.
The artifact reader retains its immutable-run cache contract.

Live-provider benchmarks, migrations, ingestion, deployment: **NOT RUN**.
No commits, pushes, PRs, credential changes or remote data mutations. The only external reads
were downloading the original font files/license from the Google Fonts repository:
https://github.com/google/fonts/tree/main/ofl/bevietnampro

Working tree remains dirty. Inherited `.codex/config.toml` and these untracked report directories
were preserved, not edited or promoted:
- `docs/evaluation/runs/retrieval-v3-case025-retry5-20260903/`
- `docs/evaluation/runs/retrieval-v3-case043-quota-retry-20260903/`
- `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-20260903/`
- `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-final-20260903/`

## Changed implementation/documentation files

- `app/api/evaluation_lab_routes.py`
- `app/api/legal_routes.py`
- `app/services/evaluation_lab.py`
- `app/static/css/vietlex-enhancements.css`
- `app/templates/admin.html`
- `app/templates/evaluation_lab.html`
- `app/templates/index.html`
- `app/templates/legal_document.html`
- `app/templates/research_workspace.html`
- `app/templates/research_workspaces.html`
- `tests/services/test_evaluation_lab.py`
- `tests/test_evaluation_lab_routes.py`
- `tests/test_legal_routes.py`
- `docs/CURRENT_ARCHITECTURE.md`
- `app/static/fonts/BeVietnamPro-Regular.ttf`
- `app/static/fonts/BeVietnamPro-SemiBold.ttf`
- `app/static/fonts/OFL.txt`
- `app/static/fonts/README.md`
- `docs/superpowers/plans/2026-09-05-research-workspace-admin.md`

This verification directory contains newly generated evidence only.
