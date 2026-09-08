# Admin redesign and Mongo originals — 2026-09-09

## Scope and evidence

Runtime/presentation change: eight admin sections, shared inspector/evaluation
navigation, real daily traffic graph, retained redaction/unknown coverage semantics,
validated pagination, strict audit failures, private temporary original files.
No corpus, provider/model, credentials, index or retention-duration change.

- Focused admin/storage/account gate: **88 passed, 3 warnings, 9.22s**.
- Broader provider-free gate: **1207 passed, 1 failed, 4 deselected, 30 warnings,
  266.61s**. The failure was a superseded source assertion expecting the old
  single admin form. Runtime source did not change after this run.
- Updated public-template gate: **10 passed, 0.21s**. It now verifies the separate
  GET account form and shared admin shell. New route tests already verify rendered
  filter actions, export links and authorization.
- Ruff/artifact/diff checks passed before the test-only assertion update; final
  check/CI and deployment status will be recorded below.
- Browser: synthetic local fixture preview only; dashboard desktop 1440px and
  mobile 390px, mobile requests/filter layout and desktop private evaluation
  inspected. Document width equalled viewport width on dashboard/requests;
  mobile menu collapses. No fixture values were written to production.
- Live Mongo original round-trip, production admin, auth two-user acceptance:
  **NOT RUN yet**. OCR/guardrail execution and model replacement are separate work.

## Read-only provider diagnosis

Using locally configured credentials, GET model catalogs returned HTTP 200 on
2026-09-09. Groq did not list `llama-3.3-70b-versatile` or `llama3-8b-8192`;
NVIDIA did not list `meta/llama-3.3-70b-instruct`. Catalog access is not generation
or production-credential proof. No generation calls were made and no models changed.
[Groq catalog documentation](https://console.groq.com/docs/models).

## Commands

PowerShell in `D:/Download/ProfessionalLegalRAG`; full suite uses Git safe-directory
environment (GIT_CONFIG_COUNT=1, key=safe.directory, value=repository absolute path).

```powershell
.venv/Scripts/python.exe -m pytest tests/test_admin_navigation.py tests/test_admin_operations.py tests/test_admin_dashboard.py tests/test_rbac.py tests/test_evaluation_lab_routes.py tests/test_workspace_originals.py tests/test_workspace_routes.py tests/test_research_database.py tests/test_account_database.py -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-admin-storage-focused-2'
.venv/Scripts/python.exe -m pytest tests -q -m 'not live' --durations=10 --junitxml=output/verification-admin-storage-20260909-tests.xml -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-admin-storage-final'
.venv/Scripts/python.exe -m pytest tests/test_public_templates.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe scripts/check_repository_artifacts.py
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
```

Focused RED was observed for new routes, audit pagination/failure, guardrail detail,
private evaluation navigation and original storage/ownership contracts. One test
fixture initially produced an oversized parametrized test ID; short IDs corrected
that test infrastructure issue before the successful focused gate.

## Delivery

Delivered commit 62fbec7a35df527c826a157e39af2fa634785d18 to origin/main. GitHub Actions run 34259865993 passed test-and-lint and build-and-push. Vercel deployment NLZM5FCBTpF1wWq1F1nTWg5XfH4n succeeded. Unrelated skill/config changes,
build/egg-info and existing evaluation run directories are preserved and excluded.

Production acceptance after deployment: authenticated /admin dashboard and /admin/system rendered real persisted values and online-only readiness. The synthetic workspace accepted admin-original-20260909.txt (215 bytes, SHA-256 0358ea0827bbe9d5ea8579ce1fe25cd23fae8f917ed97903a584e9331236b328), retained its link after reload, and clicking the owner-scoped original link emitted a browser download event. Download bytes were not accessible through the opaque browser result; a separate local Mongo hash comparison failed DNS resolution, so exact live byte round-trip is NOT VERIFIED. Unit tests verify byte/owner/expiry behavior. The test file remains until workspace expiry 2026-10-08. No provider call was used for this upload. Two verified-user acceptance remains NOT RUN pending user self-registration.
