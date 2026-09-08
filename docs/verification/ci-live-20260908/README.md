# CI dependency repair and real-provider checks — 2026-09-08

## Scope and authority

The owner explicitly authorized real API calls and previously authorized commits and
pushes to main. No credentials, production environment, persistent corpus or vectors
were changed. This change repairs CI dependency installation and adds an opt-in real
RAG regression check. It does not claim all unfinished product features are complete.

## Evidence

- Supplied GitHub failure: `pypdf` missing; 1 failed, 1,164 passed, 4 skipped in
  35.48 seconds. `requirements.txt` omitted the application's runtime dependency
  declaration. It now installs the project as well, resolving dependencies from
  `pyproject.toml`; CI checks PDF imports immediately after installation.
- Local complete provider-free run: **1 failed, 1,166 passed, 3 deselected**, 308.90s.
  Failure: `test_non_git_directory_is_typed_unavailable`, because the writable
  `--basetemp` was inside the checkout and Git correctly discovered its parent.
  Rerun outside the checkout plus PDF tests: **9 passed**, 0.70s. The original full
  run remains recorded as failed, not retrospectively relabelled green.
- JUnit summed test durations: 281.40s. Slowest call was deterministic adjudication
  regression (44.52s); content-store subprocess cases took 6–11s. Local timings differ
  materially from the supplied Linux CI result. No tests were deleted by count.
- Real Vertex generation/embedding plus configured RAG: **2 passed**, 27.47s.
  RAG retrieval status `ok`, three contexts, generation `success`, observed provider
  `google_vertex_ai`, model `gemini-3.5-flash`, 1,218 generation tokens, 6.148s pipeline
  time. Embedding/retrieval costs are not included in that generation token count.
- Additional real structured calls used Qdrant-retrieved public evidence: claim
  assessment succeeded (1/1 assessed). Research report failed once with
  `ResearchReportValidationError` / `invalid_structured_response`, then succeeded
  on two diagnostic calls. **Intermittent report schema reliability remains open**;
  the failed raw response was not captured, so its validation cause is unknown.
  Diagnostic instrumentation forwarded the real provider response unchanged;
  no provider doubles were used in these live calls.
- Ruff and changed-file whitespace checks passed; workflow YAML parsed.
- `uv --system-certs --cache-dir output/uv-ci-fix-cache pip install --dry-run --no-deps
  --python .venv/Scripts/python.exe -e .` resolved the local project. This is not a
  clean full-dependency installation proof. Local pip attempts encountered missing
  setuptools without build isolation and local CA trust failure with isolation.

## Commands

```powershell
$env:RUN_VERTEX_LIVE_TESTS='1'
.venv/Scripts/python.exe -m pytest tests/integration/test_vertex_ai_live.py tests/integration/test_rag_live.py --run-live -q -s -p no:cacheprovider --basetemp=output/pytest-live-20260908-ci-fix
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest tests -q -m 'not live' --durations=20 --junitxml=output/ci-fix-tests-20260908.xml -p no:cacheprovider --basetemp=output/pytest-ci-fix-20260908-full
.venv/Scripts/python.exe -m pytest tests/evaluation/test_provenance.py::test_non_git_directory_is_typed_unavailable tests/services/test_workspace_documents.py -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697/pytest-ci-fix-20260908'
.venv/Scripts/python.exe -m ruff check .
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check -- .github/workflows/ci-cd.yml requirements.txt
```

Local operational logs are in `output/ci-fix-*`, `output/live-ci-fix-20260908.log`,
`output/live-workspace-ci-fix-20260908.log`, and `output/diagnose-live-report*.log`.
The last two diagnostic scripts were local instrumentation, not shipped application code.

## Limits

Authenticated browser workflows, complete feature-by-feature live coverage, destructive
abuse/load testing, WAF configuration, legal accuracy certification, billing reconciliation,
OCR and corpus expansion: **NOT RUN / not established by these checks**. CI now excludes
live calls explicitly, cancels superseded runs, and preserves per-test timings as an artifact.
Vercel retains its existing runtime lock and test/evaluation bundle exclusions.
