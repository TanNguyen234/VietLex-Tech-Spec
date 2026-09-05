# Admin request observability implementation plan

**Goal:** Expose measured LLM token consumption, request/context details and honest verification in admin, then continue the report's citation verification work.
**Architecture:** Extend existing provider events with request-local capture, persist bounded metadata in evaluation logs, aggregate in MongoDB and render local Jinja views. No provider calls in reads or tests.
**Classification:** Runtime, evaluation presentation, documentation.

## Contract / authority / proof

- Authorized: local implementation and provider-free tests. No ingestion, migration, credential changes, paid benchmark or evidence promotion.
- Preserve inherited dirty files. No worktree. Review source directly because CRG is unavailable.
- Tokens are provider-reported nonnegative integers; missing is unknown, never zero. LLM counts exclude embedding/reranker billing and unreported failed attempts; reasoning is a component, never added to provider total.
- Request capture is isolated across concurrent requests and reset on exceptions. Persist no prompts or credentials in provider events.
- Admin output redacts secrets/PII, escapes HTML, labels truncation, requires admin and uses no-store.
- Context checks are deterministic structural/quote checks, not semantic correctness or legal-effect certification. Judge evaluations remain opt-in.

## Tasks

- [x] RED: tests/services/test_admin_observability.py, tests/test_admin_operations.py, tests/services/test_direct_llm.py and tests/evaluation/test_online_metrics.py: token retention, concurrent capture, missing/invalid counts, detailed escaping and long contexts.
- [x] Implement request telemetry in app/services/provider_runtime.py, app/services/direct_llm.py, app/evaluation/online_metrics.py, app/database.py and app/api/routes.py. Presentation/aggregation helpers in app/services/admin_observability.py; templates/admin*.html and static/css/admin.css.
- [x] Continue report with deterministic claim/quote verification and explicit unknown legal status, using existing research presenter and source contexts. Tests reject invented quotes and citation-only assertions of semantic support.
- [x] Review stable diff and error paths using OCR delegation; run focused gates, then full suite once after review fixes.
- [x] Generate a fresh verification report with exact commands/results, limitations, changed files and remaining roadmap; record redacted milestone reflection.

Focused gate: `.venv/Scripts/python.exe -m pytest tests/services/test_admin_observability.py tests/test_admin_operations.py tests/test_admin_dashboard.py tests/services/test_direct_llm.py tests/evaluation/test_online_metrics.py tests/services/test_research_presenter.py -q`.
Broader gate: `.venv/Scripts/python.exe -m pytest -q`.
