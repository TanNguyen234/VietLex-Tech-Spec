# Live product failures implementation plan

**Goal:** Fix reproduced production failures and verify the repaired workflows with real API calls.
**Architecture:** Keep current stores, auth and retrieval contracts. Repair scope/runtime and structured-generation boundaries; measure retrieval changes on identical inputs before promotion.
**Tech stack:** FastAPI, Pydantic, Vertex, Qdrant, MongoDB, pytest.

## Authority and boundaries
User authorizes fixes, live paid calls, commit/push/deploy. Preserve private credentials, existing data and human-only legal verification. No destructive ingestion or invented legal status. Execute sequentially in existing checkout; no additional agents.

## Tasks
- [ ] Reproduce scoped chat failure using real document and deployed packaging; add failing regression test, repair root cause, verify focused tests.
- [ ] Capture actual malformed structured responses and finish reasons; add regression for observed failure, fix shared generation contract without accepting invalid evidence IDs.
- [ ] Remove unsupported current-law claims from review contract; retain explicit unverified provenance.
- [ ] Diagnose retrieval miss and official portal queries against source; benchmark any ranking change on identical inputs, preserve failure visibility.
- [ ] Review stable diff, run broader suite, commit/push/deploy authorized fixes, rerun real workflows and report remaining failures honestly.

## Review targets
app/services/document_scope.py, app/api/routes.py; app/services/research_analysis.py, direct_llm.py, vertex_ai.py; workspace review prompts; official research query builder. Tests under tests/services and route tests. Final artifacts only after stable source/config; original live-api-af8c9f5 evidence remains historical.
