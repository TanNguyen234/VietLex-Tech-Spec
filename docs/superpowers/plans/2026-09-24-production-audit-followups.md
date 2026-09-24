# Production audit follow-ups — local implementation record

**Scope:** F01, F02, F04, F05, F06 and the nearby reference-sensitive retained-source selector from the 2026-09-24 audit. F03 has a separate [plan](2026-09-24-report-evidence-aliases.md).

**Contract and authority:** Preserve saved-source provenance, strict evidence validation, exact search filtering, CSRF, and provider-free default tests. This task authorizes local code and tests. It does not authorize production deployment, paid-provider calls, ingestion, migration, commit, push, or deletion. A failed/weak feature can only be proposed for removal and requires user approval before any removal.

**Failure cases and focused gates:**

| Finding | Focused failure observed before fix | Local change | Focused proof |
| --- | --- | --- | --- |
| F01 | Saved page with empty extraction was indistinguishable from a page never requested | Track attempted/readable pages separately; state both counts in source library | `tests/test_source_library.py` |
| F02 | Successful same-page pin could navigate only to the current hash, leaving the count stale | Reload workspace after a successful same-page pin | `node --check app/static/js/research-workspace.js`; live browser acceptance pending deployment |
| F04 | Successful structured review showed `Request hoàn tất: fail` and missing chat context/citations | Evaluate structured request status separately, show chat checks as N/A, expose clause/finding/evidence counts | `tests/services/test_public_evaluation.py`, `tests/test_admin_navigation.py`, `tests/test_full_document_review_routes.py` |
| F05 | Retained-source LLM operation absent from central token ledger | Save sanitized admin interaction with provider call ledger, selection counts, status and source hash; default omitted scope to relevant | `tests/test_retained_source_routes.py` |
| F06 | CSS uppercased visible legal type while backend exact filter expected its canonical case | Render legal-result type without case transformation | Source/CSS cascade check; live browser acceptance pending deployment |
| Reference-sensitive selection | A question about a numbered Điều could rank another Điều by overlapping words | Parse arbitrary Điều numbers and prioritize matching heading, preserving existing adjacent passage selection | `tests/services/test_retained_source_analysis.py` |

Tests for behavior changes were written first and observed RED. Source changes were made within the affected contracts. The focused gates and provider-free suite were run after the final source review. No performance or token-saving percentage is claimed without paired provider measurements.

**Completed verification:** `.venv\Scripts\python.exe -m pytest tests/test_source_library.py tests/test_retained_source_routes.py tests/services/test_retained_source_analysis.py tests/services/test_public_evaluation.py tests/test_admin_navigation.py tests/test_full_document_review_routes.py tests/services/test_research_report.py tests/test_research_report_routes.py tests/test_report_deliverables.py -q -p no:cacheprovider` → 87 passed, 2 warnings. `node --check app/static/js/research-workspace.js` → passed. `git diff --check` → passed (Git printed only line-ending warnings). After stable source review, `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` → 1,405 passed, 4 skipped, 31 warnings in 211.86 seconds. Integration with actual database/provider and production browser acceptance: NOT RUN.

## Decision boundary

The audit's 7/7 failed retained reports justify treating AI report generation as **unverified on production**, but the local F03 alias mitigation has not been exercised live. That is insufficient evidence to delete the feature. If a fresh, authorized same-input benchmark still fails its agreed success and token criteria, propose disabling or removing report generation with the failed cases, costs, and alternative workflow for the user's approval. The offline body-search gap requires index/coverage decisions, not feature deletion. No feature is removed in this change.
