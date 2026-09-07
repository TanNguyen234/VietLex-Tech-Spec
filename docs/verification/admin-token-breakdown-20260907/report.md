# Admin token breakdown — 2026-09-07

Delivered: independent input/output/thinking/total token coverage for retained provider/model/use-case groups. Mongo aggregation now uses the same bounded nonnegative integer guard as request summaries; missing, boolean, fractional and invalid token values are not observations. Measured zero remains zero; no measurement renders N/A. Dropped calls are disclosed globally because their provider/model/use case cannot be recovered. Existing tokens/measured aliases remain compatible.

## Changed files

- app/services/admin_observability.py
- app/templates/admin_quality.html
- tests/services/test_admin_token_breakdown.py
- docs/superpowers/plans/2026-09-06-admin-token-breakdown.md
- This report and manifest.

## Verification

- RED: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/services/test_admin_token_breakdown.py`: 2 expected failures before implementation.
- GREEN: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/services/test_admin_token_breakdown.py tests/services/test_admin_observability.py`: 13 passed, 4 existing deprecation warnings.
- `.venv/Scripts/python.exe -m ruff check app/services/admin_observability.py tests/services/test_admin_token_breakdown.py`: all checks passed.
- `git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check -- app/services/admin_observability.py app/templates/admin_quality.html`: exit 0.
- Independent stable diff review: no remaining P1/P2. First attempt was interrupted by quota; resumed review completed on September 7. CRG tools unavailable; direct source/diff review used.
- Full suite, after clean review: **1067 passed, 2 skipped, 16 existing deprecation warnings, 410.39 seconds**, exit 0.

Exact full command (PowerShell, environment scoped to that process):

```powershell
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = 'D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697/pytest-admin-token-20260907-01'
```

No source/configuration edit followed the full suite. Manifest covers the changed source/test files including the untracked test. Inherited .codex/config.toml and four pre-existing evaluation run directories are excluded from this change.

## Limits and remote effects

Unit/provider-free tests and Jinja rendering only. Live Mongo aggregation, deployment, browser screenshot and paid/live-provider calls: **NOT RUN**. No fabricated billing estimates or recovered usage. At most 50 groups are displayed, under existing request filters and retention. Full upstream retry/embedding/reranker accounting remains outside this LLM ledger's measured scope. Commit/push authorized to TanNguyen234/VietLex-Tech-Spec main; final Git result reported separately.
