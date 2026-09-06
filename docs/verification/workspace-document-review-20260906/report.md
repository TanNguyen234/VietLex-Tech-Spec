# Workspace document review verification — 2026-09-06

## Delivered

Owner-scoped PDF/DOCX/UTF-8 TXT upload, clause inventory and pinning, selected-clause structured contract review, and explicit error states. Contract review admin telemetry retains hashes/counts/status rather than copied private clauses or findings. Workspace data shares its retention boundary; deleting a document removes its direct review analyses and pins.

Limits: 10 MiB input, 250,000 extracted characters, 100 segments, 20 documents, atomic conservative 12 MB BSON budget. Parser subprocess: 256 MiB memory and 15-second deadline. Upload ingress: 2 concurrent bodies, 6 per IP per minute, 30-second body deadline. Limits are per application process, not a distributed quota.

## Evidence

- Focused RED observed for parser/module absence and persistence/privacy regressions; focused GREEN: 51 passed before two additional middleware cases.
- Independent stable review: no remaining P1/P2 in five repaired boundaries; reviewer focused validation 6 passed, 2 deselected.
- `.venv/Scripts/python.exe -m ruff check app tests`: all checks passed.
- `node --check app/static/js/research-workspace.js`: exit 0.
- `git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check`: exit 0; line-ending warnings only.
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`: interrupted after repeated tmp_path PermissionError against the previous Windows identity's temporary directory; not a passing run.
- `.venv/Scripts/python.exe -m pytest -x -q -p no:cacheprovider`: confirmed the same environment error.
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp="C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697/pytest-document-review-20260906-01"`: **1064 passed, 2 skipped, 1 failed**, 16 warnings, 379.99 seconds. The failure was Git dubious ownership in the pre-existing immutable-artifact checkout test.
- Retried only that failure with process-local `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=safe.directory`, `GIT_CONFIG_VALUE_0=D:/Download/ProfessionalLegalRAG`: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/evaluation/test_gold_adjudication.py::test_adjudication_json_artifacts_are_checked_out_with_lf_bytes`: **1 passed**, 0.46 seconds. No global Git configuration changed. No source/config edits followed full execution.
- Real Windows process-memory probe: invoke `_limit_memory()` then allocate `bytearray(300 * 1024 * 1024)`; observed `MemoryError` and `MEMORY_LIMIT_ENFORCED` (exit 0).

This is full-suite coverage plus one environment-corrected retry, not a claim that a single full invocation was entirely green. Unit tests use database/provider doubles. The parser worker tests exercise a real local subprocess. Earlier UI preview used synthetic content; no final production screenshot is claimed.

## Limits and remote effects

Live MongoDB validation, paid generation, OCR, live-provider benchmark, and deployment: **NOT RUN**. PDF scan OCR is unsupported. `evidence_linked` means references are selected and valid identifiers, not proof of legal correctness. Review covers selected clauses only. No corpus ingestion, migration, or evidence promotion.

Commit/push authorized by the user's earlier instruction; delivery Git result is reported separately. Inherited `.codex/config.toml` changes and four pre-existing untracked evaluation run directories are excluded.

## Changed files

- `app/api/workspace_routes.py`
- `app/main.py`
- `app/research_database.py`
- `app/services/http_security.py`
- `app/services/research_analysis.py`
- `app/services/document_worker.py`
- `app/services/workspace_documents.py`
- `app/static/css/vietlex-enhancements.css`
- `app/static/js/research-workspace.js`
- `app/templates/admin_details.html`
- `app/templates/research_workspace.html`
- `docs/CURRENT_ARCHITECTURE.md`
- `pyproject.toml`
- `tests/services/test_research_analysis.py`
- `tests/services/test_document_worker.py`
- `tests/services/test_upload_body_limit.py`
- `tests/services/test_workspace_documents.py`
- `tests/test_public_templates.py`
- `tests/test_research_database.py`
- `tests/test_workspace_routes.py`
- `docs/superpowers/plans/2026-09-05-workspace-document-review.md`
- This report and manifest.
