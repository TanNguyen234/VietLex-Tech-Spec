# Admin request observability verification

## Scope

This change turns the existing administrator page into a request-level observability workspace. It records and presents bounded request metadata, provider/model calls, token usage and coverage, retrieval stages, returned contexts, deterministic citation checks, optional judge results, guardrail outcomes, feedback, latency, failures, and account/session inventory.

The implementation preserves three explicit unknown states:

- missing provider usage is excluded from token totals and counted as uncovered;
- semantic support remains `NOT_EVALUATED` unless a judge actually ran;
- legal-effect status remains `UNKNOWN` unless an authoritative status check exists.

No provider, ingestion, migration, credential, or production write was used for verification.

## Source identity

- Base Git commit: `7060ee38f5b0f8af327c1b984d1991db5e6c8ed5`
- Working tree at verification: dirty by design
- Admin change-set SHA-256 recorded before this report: `7fc38ca6e5aa87787f826663cef9d9cd616532f87dccd03dc2c2cdd9ba9266d1`
- Verification time: `2026-09-05T22:43:20+07:00`

## Changed source and tests

- `app/api/routes.py`
- `app/database.py`
- `app/evaluation/online_metrics.py`
- `app/services/admin_observability.py`
- `app/services/direct_llm.py`
- `app/services/evaluator.py`
- `app/services/http_security.py`
- `app/services/provider_runtime.py`
- `app/services/rag_pipeline.py`
- `app/static/css/admin.css`
- `app/templates/admin.html`
- `app/templates/admin_details.html`
- `app/templates/admin_filters.html`
- `app/templates/admin_inventory.html`
- `app/templates/admin_logs.html`
- `app/templates/admin_quality.html`
- `app/templates/admin_stats.html`
- `app/templates/admin_usage.html`
- `docs/CURRENT_ARCHITECTURE.md`
- `docs/superpowers/plans/2026-09-05-admin-request-observability.md`
- `tests/evaluation/test_online_metrics.py`
- `tests/services/test_admin_observability.py`
- `tests/services/test_direct_llm.py`
- `tests/services/test_evaluator.py`
- `tests/test_admin_operations.py`
- `tests/test_product_navigation.py`
- `tests/test_public_templates.py`
- `tests/test_rag_pipeline.py`

## Verification

### Unit and repository tests

Command:

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Result: `1027 passed, 2 skipped, 14 warnings in 256.05s`; exit code 0.

The first broad run exposed two compatibility failures: legacy direct template rendering lacked the new usage shape, and a navigation assertion still expected fragment-only filtering. Both were corrected, focused regressions passed, and the full suite above was rerun after the final source edit.

### Static analysis

Command:

```powershell
.venv/Scripts/python.exe -m ruff check app tests
```

Result: passed; exit code 0.

Command:

```powershell
git diff --check
```

Result: passed; exit code 0. Git emitted only the repository's Windows LF-to-CRLF notices.

### Read-only MongoDB integration

A bounded aggregation probe used `$limit: 1` followed by a literal projected fixture. It did not read raw question, answer, or context content and performed no writes.

Observed result:

```text
{"aggregation":"available","inventory":"available"}
{"case":0,"matched_python_contract":true}
{"case":1,"matched_python_contract":true}
{"case":2,"matched_python_contract":true}
{"case":3,"matched_python_contract":true}
```

This verifies the production Mongo server accepts the aggregation operators used for valid, malformed numeric, missing, and scalar legacy token ledgers.

### Browser verification

A local test-only fixture rendered the admin overview and request detail in a headless browser and the in-app browser. No production data was used.

- desktop overview and detail rendered the usage, quality, inventory, filters, request, context, retrieval, judge, guardrail, and feedback sections;
- at a 390 px viewport, both pages reported a 390 px document width after the responsive fix;
- the primary navigation link contrast was corrected after visual review.

### Independent review

Open Code Review delegation and an independent reviewer checked the stable diff. Findings addressed before the final suite:

- capture optional Ragas chat-completion usage;
- report dropped provider-call events instead of implying complete coverage;
- avoid rendering unavailable aggregates as zero;
- prevent mobile table/detail overflow;
- increase primary navigation contrast;
- normalize malformed legacy Mongo token ledgers before aggregation.

Final review status: no open Important findings.

## Operational boundaries

- Live LLM/provider calls: **NOT RUN**.
- Live retrieval calls: **NOT RUN**.
- Database writes or migrations: **NOT RUN**.
- Full-corpus ingestion or vector changes: **NOT RUN**.
- Screenshots were generated from explicitly labelled synthetic fixture data and kept outside the repository.
- Existing records created before this change can legitimately show token coverage as unknown.
- Exact quote/citation membership is deterministic structural evidence; it is not presented as semantic or legal correctness.

## Preserved user work

The following inherited changes were excluded from this change set:

- `.codex/config.toml`
- `docs/evaluation/runs/retrieval-v3-case025-retry5-20260903/`
- `docs/evaluation/runs/retrieval-v3-case043-quota-retry-20260903/`
- `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-20260903/`
- `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-final-20260903/`
