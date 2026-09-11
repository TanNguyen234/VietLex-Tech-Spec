# Product reliability — local verification, 2026-09-11

This records implementation and provider-free checks, not deployment or legal-quality acceptance. Current capability inventory and remaining work: [FEATURE_STATUS](../../FEATURE_STATUS.md). Scope/authority: [implementation plan](../superpowers/plans/2026-09-10-product-reliability.md).

## Outcome and additional findings

- Document Q&A now resolves a selected document on the server, restricts lexical evidence to it, skips corpus retrieval/rewrite and semantic cache, and refuses when no matching evidence exists. Scoped citation presentation retains the document ID. Reader pinning checks workspace ownership and copies the section from the server, not client-supplied evidence.
- Legal-effect processing distinguishes amendment and partial termination after a reviewed effective event. Duplicate source IDs are rejected rather than overwriting provenance. This remains a reviewer event workflow, not a corpus-wide verified status registry.
- Search filters are applied before LIMIT on both metadata backends. Neither metadata search nor a bounded scan is advertised as full-text body retrieval.
- Workspace panels organize existing tools into seven tasks. Completed document review switches to Review so its result is not hidden by the Documents panel. Model comparison requires admin at the API and UI; the end-user safety checkbox is removed. Configured guardrail checks cannot be disabled through a submitted false value or bypassed by a cached answer.
- Findings preserve the original generated result while reviewer decisions have optimistic concurrency and bounded history. Report edits create new unverified versions with source snapshots; exports support Markdown/basic DOCX and browser printing for PDF.
- Admin corpus exposes a factual read-only metadata quality queue. Feedback supports categorization, assignment labels, investigation/resolution history and a regression draft whose expected answer is intentionally empty until human adjudication.
- Optional Brave discovery runs beside the direct government portal, filters official domains, deduplicates URLs and retains partial provider errors. It defaults OFF; it does not imply all-domain full-page reading or legally verified evidence.
- Documentation drift is corrected with one current status file. Historical reviews are explicitly snapshots. No historical benchmark artifact was rewritten.

## Verification commands and results

All commands run from `D:\Download\ProfessionalLegalRAG`. Python is the repository `.venv`. External provider connections are blocked by the default test fixture; no `--run-live` was used.

### Focused implementation checks

```powershell
.venv/Scripts/python.exe -m pytest tests/services/test_document_scope.py::test_document_scope_never_calls_corpus_retrieval tests/test_legal_routes.py::test_reader_pin_resolves_source_on_server_and_checks_workspace_owner -q -p no:cacheprovider
```

RED observed: missing document ID and missing pin endpoint, 2 failures. After implementation:

```powershell
.venv/Scripts/python.exe -m pytest tests/services/test_document_scope.py tests/test_legal_routes.py tests/test_workspace_routes.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_product_quality.py tests/test_finding_management.py tests/test_report_deliverables.py -q -p no:cacheprovider
```

Results: **32 passed** and **7 passed** respectively. Earlier focused legal effect/search/federation/report gates were also run; the broader run below covers their final runtime state.

### Broader suite and failure investigation

```powershell
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.tmp-product-final-20260911
```

First broader result: **1253 passed, 5 failed, 4 skipped** in 307.63 seconds. Failures:

1. New finding/report full pages lacked the shared redesign stylesheet. Fixed both templates.
2. Git subprocess in the adjudication attribute test rejected workspace ownership. Applied process-only `safe.directory` for the test invocation; no global Git setting changed.
3. Two structural pilot tests could not hash nested Git fixtures stored inside the repo basetemp. Added a narrow `.gitignore` rule for `/.tmp-product-*/`; no production provenance exception or file deletion.
4. Decision artifact source fingerprint changed when test outputs were visible as untracked source. The narrow basetemp ignore and stable source state address this; original production hashing remains intact.

```powershell
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest tests/evaluation/test_decision_package.py::test_same_inputs_produce_byte_identical_decision_artifacts tests/evaluation/test_gold_adjudication.py::test_adjudication_json_artifacts_are_checked_out_with_lf_bytes tests/ingestion/test_structural_pilot.py::test_provider_free_cli_writes_audit_and_blocks_unproven_capacity tests/test_redesign_navigation.py tests/test_finding_management.py tests/test_report_deliverables.py -q -p no:cacheprovider --basetemp=.tmp-product-corrected-20260911
```

Result: **11 passed**. Then, with the same process-only Git environment:

```powershell
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.tmp-product-verified-20260911
```

Second broader result: **1257 passed, 1 failed, 4 skipped** in 248.26 seconds. The remaining failure was `test_non_git_directory_is_typed_unavailable`: a basetemp under the checkout lets Git discover the parent repository. Fixed the test by setting `GIT_CEILING_DIRECTORIES` only through its monkeypatch fixture. Production code unchanged.

```powershell
.venv/Scripts/python.exe -m pytest tests/evaluation/test_provenance.py -q -p no:cacheprovider --basetemp=.tmp-product-provenance-20260911
```

Result: **15 passed**. The full suite was not rerun after this test-only isolation fix. Do not describe the second broader invocation as zero failures. All identified failures have a passing focused recheck; runtime source stayed unchanged after that broader run.

### JavaScript, documents and browser

```powershell
& 'C:/Program Files/nodejs/node.exe' --test tests/product_forms.test.cjs
& 'C:/Program Files/nodejs/node.exe' --check app/static/js/research-workspace.js
git -c safe.directory=D:/Download/ProfessionalLegalRAG -c core.safecrlf=false diff --check
.venv/Scripts/python.exe tests/visual/redesign_preview.py
```

- Node forms: **5 passed**; JavaScript syntax and diff whitespace checks passed.
- A synthetic in-memory DOCX was opened as ZIP and all 3 XML parts parsed with `xml.etree.ElementTree`; this is not a Word interoperability check.
- Browser CUA inspected the synthetic localhost workspace: Overview initially, Reports after tab selection; unrelated analysis forms were hidden. Preview initially needed restarting after a refused connection. No live application data or generated provider result was used.
- All 30 test file references in FEATURE_STATUS resolve.
- Deprecation warnings remain for Starlette httpx TestClient, naive `datetime.utcnow`, FastAPI startup events and per-request test cookies. No provider/live run was performed to address these unrelated warnings.

## Changed files in this work

Runtime/API: `app/api/legal_routes.py`, `model_comparison_routes.py`, `research_report_routes.py`, `routes.py`, `workspace_routes.py`; new `finding_routes.py`, `product_quality_routes.py`; `app/config.py`, `app/main.py`, `app/research_database.py`.

Services: `app/services/legal_browser.py`, `legal_effect.py`, `official_web_search.py`, `deep_research.py`, `rag_pipeline.py`; new `document_scope.py`, `federated_official_search.py`, `report_deliverables.py`.

UI: `app/static/css/vietlex-enhancements.css`, `app/static/js/product.js`, `research-workspace.js`; templates `admin_sidebar.html`, `index.html`, `legal_document.html`, `legal_search.html`, `research_tools.html`, `research_workspace.html`; new `admin_corpus_queue.html`, `admin_feedback_queue.html`, `finding_board.html`, `report_editor.html`.

Tests: `tests/services/test_legal_browser.py`, `test_legal_effect.py`; new `test_document_scope.py`, `test_federated_official_search.py`; `tests/test_legal_routes.py`, `test_model_comparison_routes.py`, `test_public_templates.py`, `test_public_web_routes.py`, `test_workspace_routes.py`; new `test_finding_management.py`, `test_product_quality.py`, `test_report_deliverables.py`; `tests/evaluation/test_provenance.py`.

Documentation/support: `.gitignore`, `README.md`, new `FEATURE_STATUS.md`; `docs/PROJECT_CONTEXT.md`, `CURRENT_ARCHITECTURE.md`, `REVIEWER_GUIDE.md`, `UNFINISHED_FEATURES_REVIEW_20260908.md`; implementation plan and this verification record.

## Git, authority and remaining acceptance

Branch **main**, HEAD **84ce93d2372a2b5884d12e49aa663da9ce10b150**, dirty throughout. Existing redesign/observability changes, skill/config changes, untracked fonts/build/visual fixtures and evaluation runs were preserved. The file list above identifies this work, not ownership of every pre-existing diff in those files. The companion source-state JSON snapshots the dirty tree after this report was written and before the JSON itself existed; it is not a benchmark run manifest.

No commit, push, merge, PR, production deployment, `.env`/credential modification, full ingestion, migration, vector/index mutation, paid provider call or human-only evidence promotion. Live Mongo concurrency, legal source verification, multi-account production acceptance, Brave/OCR/provider quality, Word GUI and PDF export: **NOT RUN**.

The complete original report is **not fully implemented**. Full-text/article search and highlighting, corpus-wide verified lifecycle data/as-of, ingestion/reindex/rollback administration, v2 finding reconciliation and richer report/citation exports remain open as specified in FEATURE_STATUS. These are not hidden behind a production-ready claim.
