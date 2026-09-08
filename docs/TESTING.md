# Test execution

Latest functional evidence (2026-09-08): [commands and gates](verification/feature-live-20260908/commands.md),
[feature matrix and live limits](verification/feature-live-20260908/README.md).
The final local provider-free run passed 1,180 tests; its basetemp was outside
the checkout. Live integration remains opt-in and requires a bounded provider budget.

Install development/evaluation dependencies with `python -m pip install -r requirements.txt`.
This also installs the application from `pyproject.toml`, including the PDF parser.
Deployment continues to use `requirements-demo.lock`; evaluation dependencies and tests
are excluded from the Vercel bundle.

While editing, run the affected test files. Run the complete provider-free suite once
after the change is stable; do not repeat it for every review iteration.

```powershell
.venv/Scripts/python.exe -m pytest tests/services/test_workspace_documents.py -q
.venv/Scripts/python.exe -m pytest tests -q -m "not live" --durations=20
```

CI retains regression coverage, cancels superseded runs on the same ref, and uploads
JUnit results with per-test timings. The supplied failing CI log ran 1,169 cases in
35.48 seconds; test count alone does not justify deleting coverage. Measure collection,
dependency installation and test execution separately before changing the gate.
Live checks are explicitly excluded from the default CI command.

Real-provider checks require credentials loaded by the existing application configuration:

```powershell
$env:RUN_VERTEX_LIVE_TESTS='1'
.venv/Scripts/python.exe -m pytest tests/integration/test_vertex_ai_live.py tests/integration/test_rag_live.py --run-live -q -s
```

These checks invoke real generation, embedding and configured retrieval. The RAG test
uses one public query, disables rewriting, has a 180-second deadline, and checks
nonempty evidence/answer, successful generation and observed token usage. Provider
retries/fallbacks remain subject to application configuration. It prints operational
metadata rather than credentials or private user content. Passing does not establish
legal accuracy, authenticated end-to-end coverage, billing reconciliation or full-corpus
quality. Unit tests remain necessary for failure and authorization paths that should
not be induced against production. Full ingestion and destructive operations are not
part of either command.
