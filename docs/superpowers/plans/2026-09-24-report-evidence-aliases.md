# Report Evidence Aliases Implementation Plan

**Goal:** Reduce report-generation failures caused by model transcription of selected evidence IDs while preserving strict server-side source validation.

**Architecture:** Give each selected evidence record a short, per-request alias in the model prompt. Validate every model-returned alias against that request's alias set, then replace aliases with original IDs before claim verification, persistence, preview, or export. Keep the existing failure path for unknown references and provider errors.

**Tech Stack:** Python, Pydantic, pytest, FastAPI/Jinja existing code.

## Global Constraints

- Scope: F03 report generation only. This is a runtime behavior change; no provider/model, retrieval, vector, credential, deployment, or production-data changes.
- Authority: the user requested gradual fixes; no commit, push, deployment, live paid-provider run, or feature removal was authorized.
- No new dependencies. No legal conclusion or verification may be inferred from a valid identifier alone.
- Preserve the existing maximum of ten selected evidence records and all output validation and diagnostics.

---

### Task 1: Server-owned short evidence aliases

**Files:**
- Modify: `tests/services/test_research_report.py`
- Modify: `app/services/research_report.py`

**Interfaces:**
- Consumes: `generate_research_report(question: str, evidence: list[dict]) -> dict` and existing `build_selected_evidence_prompt`.
- Produces: the same public result shape, with original evidence IDs in `report.sources`, each claim, and claim-verification input.

- [x] Add a focused test where selected IDs are long opaque strings and the simulated model returns `E1`/`E2`. It checks that the prompt has aliases, the result has original IDs, and `verify_claims` receives original evidence.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/services/test_research_report.py::test_report_maps_short_prompt_aliases_back_to_selected_evidence -q -p no:cacheprovider`; observed RED on the missing `[E1]` alias.
- [x] In `generate_research_report`, create per-request `E1`…`E10` copies for the prompt, validate model references against aliases, and replace them with original IDs before verification or response construction. State the allowed aliases and union rule for `sources` in the prompt.
- [x] Keep the existing unknown-ID test: an unknown alias yields `invalid_evidence_reference` and never invokes `verify_claims`.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/services/test_research_report.py tests/test_research_report_routes.py tests/test_report_deliverables.py -q -p no:cacheprovider`: 19 passed. Reviewed the stable diff and failure branches.
- [x] Run `.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` once after source review: 1,397 passed, 4 skipped, 31 warnings in 324.19 seconds. Live production verification remains pending deployment authorization.

## Self-review

- The alias map is local to one request and cannot add evidence outside the selected list.
- Original evidence IDs leave the service in every persisted or exported report field.
- The report validator still rejects an unknown alias, incomplete source list, invalid schema, truncated output, and a verifier quote mismatch.
- Existing surrounding routes, preview/export, and sanitised diagnostics remain unchanged unless focused tests expose a necessary compatibility change.
