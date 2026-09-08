# Admin redesign and remaining acceptance implementation plan

> **For agentic workers:** Execute inline task by task using the available project TDD/review workflow. The referenced superpowers execution skills are not installed; no worktree or agent dispatch is required.

**Goal:** Deliver a professional multi-page admin backed by real operational data, then close remaining runtime and acceptance gaps within available authority.
**Architecture:** Keep FastAPI/Jinja SSR and current repositories. Reuse a shared admin shell, separate page-specific reads, preserve partial endpoints and account mutation protections. Runtime/evaluation/corpus contracts remain pinned.
**Tech Stack:** Python 3.12, FastAPI, Jinja, local CSS/JS, Mongo repositories, provider-free pytest.

## Global constraints

- Preserve CSRF, require_admin, no-store, bounded queries, redaction and unknown/coverage semantics.
- No corpus migration/deletion, credential change or unbudgeted generation calls. Existing 12-call allowance is exhausted.
- Existing unrelated working changes stay untouched. No worktree.
- Source/test/config outrank historical docs. This is runtime/presentation work, not benchmark promotion.

## Task 1: Admin navigation, data boundaries and dashboard

Files: app/api/routes.py; app/templates/admin.html, admin_base.html, admin_sidebar.html, admin_requests_page.html, admin_usage_page.html, admin_users_page.html, admin_providers_page.html, admin_system_page.html, admin_audit_page.html; existing admin partials; app/static/css/admin.css; tests/test_admin_navigation.py; tests/test_admin_operations.py.

- [ ] RED: GET /admin/requests and /admin/usage must return authenticated full pages; assert no unrelated user/audit/readiness reads. All dedicated routes reject normal users before readers execute.
- [ ] Implement /admin as compact dashboard (four KPI cards, actual daily traffic chart, error summary, recent requests, links). Each dedicated page only queries its data. Use the existing admin_filters contract with form action matching the page.
- [ ] Reuse a sidebar/header shell with active aria-current, skip link, responsive navigation, local assets and dark-mode support. Use HTML/CSS plots plus accessible tabular values, no fabricated trends.
- [ ] GET /admin/users and /admin/audit become full pages. Preserve existing /admin/logs and /admin/stats partials. Validate user search/status/role/skip/limit; provide previous/next pages. Account mutation redirects to /admin/users. Reuse CSRF cookie across navigation; create securely if absent.
- [ ] Add strict audit read/error handling and bounded offset pagination; a database failure must not say there are no logs.
- [ ] GREEN: pytest tests/test_admin_navigation.py tests/test_admin_operations.py tests/test_admin_dashboard.py tests/test_rbac.py.

Example RED contract:
```python
def test_requests_page_does_not_fetch_accounts(client, readers):
    response = client.get('/admin/requests?model=example')
    assert response.status_code == 200
    assert 'aria-label="Điều hướng quản trị"' in response.text
    readers['list_users'].assert_not_awaited()
    assert readers['get_admin_logs'].await_args.kwargs['model'] == 'example'
```

## Task 2: Consistent inspectors/evaluation and truthful operational states

Files: app/templates/admin_details.html, evaluation_lab.html; app/api/evaluation_lab_routes.py; relevant evaluation/admin tests.

- [ ] Shared navigation and active state on request detail and private Evaluation Lab; public Evaluation Lab keeps public shell.
- [ ] Display guardrail execution as unavailable on technical-error stage instead of implying success from boolean defaults. Provider configuration and telemetry exporter configuration remain separate from observed health.
- [ ] Verify preserved redaction, full evidence excerpts, metrics coverage, missing artifacts and no provider calls while reading dashboards.
- [ ] Review stable diff, run full provider-free suite once, inspect real desktop/mobile browser pages, then record evidence and push under existing authorization.

## Task 3: Remaining project work, conditional on resources

- [ ] Diagnose provider availability/export authorization via read-only runtime logs and dashboards; no credential mutation without a concrete approved change.
- [ ] Choose OCR/storage/guardrail worker topology from user-provided infrastructure. Implement only a real supported backend with ownership, bounds and retention; no production stubs or invented access.
- [ ] Obtain two test identities for auth/owner acceptance, respecting the protected admin and user's email self-check preference.
- [ ] Prepare small explicit live acceptance inputs for selected answer, obligations, compare and chat. Request a fresh bounded provider allowance only for the concrete ready tests.
- [ ] Preserve benchmark scope and expert legal-review requirements. Corpus expansion requires separate migration/ingestion authorization.

Evidence is written after source stabilizes. Do not declare all project gaps closed while operational/expert dependencies remain unresolved.

## Follow-on runtime scope frozen 2026-09-09

- Admin/Mongo originals committed/pushed as 62fbec7; Vercel success. No VPS available.
- Serverless guardrail self-check mirrors versioned NeMo prompts and the current primary model
  without retry/fallback; explicit runtime selection, strict complete yes/no decision, timeout as
  typed technical error. Existing container NeMo/evaluation modes remain unchanged.
- OCR: explicit opt-in on the existing upload form, PDF only <=5 pages /3.7 MB,
  one inline Vertex request (no Files API, no worker, no fallback/retry), <=8192
  output tokens, schema/page-order validation, hash/page provenance, machine text
  visibly unverified. Save original and extracted record atomically only on success.
  Default extraction makes zero generation calls. Invalid/error/truncated OCR must
  preserve typed status/usage and never masquerade as complete text.
- Tests first: inline PDF transport/bounds, default zero OCR, strict page coverage,
  owner/CSRF routes, metadata visibility and no private bytes in HTML/logs.
- Model replacements require identical-input bounded A/B and new paid-call authority;
  current Llama aliases were absent from both provider catalogs on read-only checks.

2026-09-09 execution update: tasks 1–2 delivered in 62fbec7 (CI/Vercel success). User approved 24 additional synthetic/public generation attempts. OCR passed two image-PDF samples; guardrail exact prompt-label parser corrected after live diagnosis; Groq primary replacement passed identical-input date/amount A/B, NVIDIA candidate failed and is not promoted. Two-user acceptance awaits self-registration.
