# Commands, gates and changed files

Commands ran from `D:/Download/ProfessionalLegalRAG` using Python 3.12.4.
External basetemp is mandatory here: default user Temp was inaccessible and a
basetemp inside the checkout breaks tests requiring a non-Git directory.

```powershell
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest tests -q -m 'not live' --durations=10 --junitxml=output/verification-20260908-json-tests.xml -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-json-final'
```

Result: **1179 passed, 4 deselected, 30 warnings in 362.55s**. Warnings were
deprecations (datetime.utcnow, FastAPI lifecycle, TestClient/cookies), not failures.
Earlier stable report fix full suite: **1171 passed, 4 deselected, 20 warnings in
253.67s** with `--junitxml=output/verification-20260908-tests.xml` and external
basetemp ending `pytest-final`. Later source changes invalidated that gate and
caused the final full run above.

Focused TDD evidence: report/claim/routes 22 passed after diagnostic/truncation
regressions; JSON-mode/database tests initially failed the intended contracts,
then 36 passed with external basetemp; full-review invalid-reference regression
initially failed, then six route tests passed. One intermediate focused run also
had a Temp permission error; it is not counted as a source regression.

```powershell
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe scripts/check_repository_artifacts.py
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
$env:VERTEX_MAX_RETRIES='0'
.venv/Scripts/python.exe -m pytest tests/integration/test_research_report_live.py --run-live -q -s -p no:cacheprovider
$env:PYTHONPATH='.'
.venv/Scripts/python.exe output/probe_report_20260908.py
.venv/Scripts/python.exe output/probe_review_20260908.py
.venv/Scripts/python.exe output/http_smoke_20260908.py
```

Ruff/artifact/whitespace passed. The opt-in live integration returned **1 passed
in 23.17s**, report STOP, 576 input/130 output/736 thinking/1442 total, 2/2 claims
assessed. Diagnostic probes used synthetic or public evidence and bounded calls;
they are not benchmarks. Raw model responses were not stored in this report.
Probe scripts and synthetic file-generation helpers are ignored under `output/`.

Post-20d0159 HTTP smoke (system trust SSL, no cookies, sequential requests):

| Request | Observed status | Detail |
|---|---|---|
| GET /healthz | 200 | 1.172 s |
| GET /readyz | 200 | 1.093 s |
| GET /admin | 401 | no-store, 1.469 s |
| GET /settings | 401 | 0.563 s |
| GET /workspaces/524d5a44-41b6-41ac-964d-7c73ebaeb284 | 404 | 0.796 s |
| POST /chat, guest synthetic question | 401 | demo_login_required |
| POST /login, synthetic credentials + invalid CSRF | 403 | CSRF token validation failed; no email sent |

Default httpx SSL trust initially failed; using the application's
`system_ssl_context()` passed, without disabling certificate validation. One
GitHub API status read disconnected; browser/connector checks supplied actual CI
evidence instead. Browser navigation/CDP timeouts are not application successes.

## Runtime and test files

Commit `d7ec81c`:

- `app/services/structured_diagnostics.py`
- `app/services/research_report.py`
- `app/services/claim_verification.py`
- `app/api/research_report_routes.py`
- `tests/services/test_research_report.py`
- `tests/services/test_claim_verification.py`
- `tests/test_research_report_routes.py`
- `tests/integration/test_research_report_live.py`

Commit `20d0159`:

- `app/services/vertex_ai.py`
- `app/services/direct_llm.py`
- `app/database.py`
- `app/api/full_document_review_routes.py`
- `tests/services/test_vertex_ai.py`
- `tests/services/test_direct_llm.py`
- `tests/test_database.py`
- `tests/test_full_document_review_routes.py`

```powershell
git -c safe.directory=D:/Download/ProfessionalLegalRAG commit -m 'fix: diagnose structured report failures and bound truncation recovery'
git -c safe.directory=D:/Download/ProfessionalLegalRAG push origin main
git -c safe.directory=D:/Download/ProfessionalLegalRAG commit -m 'fix: enforce structured Vertex JSON and surface review failures'
git -c safe.directory=D:/Download/ProfessionalLegalRAG push origin main
```

Pushes used the approved escalated Git invocation after sandbox credential-helper
failure/direct confirmation. CI for d7ec81c: run 34249923420, both jobs success.
CI for 20d0159: run 34252348259, both jobs success. No local Docker daemon run,
restore test, large benchmark or vector migration was performed.


## Final guardrail packaging regression

Runtime source additionally changes `app/api/routes.py` and `tests/test_api_routes.py`
in commit `8cbd948`. Observed Vercel guarded chat was HTTP 500 on d7ec81c;
source shows serverless dependencies/config exclude NeMo. The local missing-import
regression failed with ModuleNotFoundError, then the focused command passed 25 tests:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_api_routes.py tests/test_public_web_routes.py -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-guardrail-focused'
.venv/Scripts/python.exe -m pytest tests -q -m 'not live' --durations=10 --junitxml=output/verification-20260908-guardrail-tests.xml -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-guardrail-final'
```

The same Git safe-directory environment shown above was set for the full command.
**1180 passed, 4 deselected, 30 warnings in 255.50s.** Ruff/artifact/diff checks
passed. No paid-provider tests were repeated after this fail-closed change.
Earlier 1179-test and live evidence describes the preceding source revision.
