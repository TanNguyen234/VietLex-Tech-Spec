# Online full-text adapter and Logfire — 19/09/2026

## Implemented and tested

The serverless browser now has an opt-in PostgreSQL RPC adapter, gated by `SUPABASE_BODY_SEARCH_ENABLED=false` by default. It uses the public read-only Supabase key, applies phrase/metadata/date/sort/pagination parameters, escapes highlight spans, and rejects invalid/unavailable coverage. An unpublished batch is unavailable, not an empty successful search. The SQL query checks current source hashes under RLS before LIMIT. No bundled local fallback is introduced.

The new CLI prepares an immutable bounded batch from hash-verified ContentStore documents. Global document offsets are checked against exact source slices. Existing output is never overwritten. Upload is an explicit command; it stages a new batch, supports resume only against matching remote metadata, and publishes only with `--publish`. SQL verifies counts, hashes and exact body offsets atomically before switching the active generation; old generations are not deleted.

- Focused unit/route checks: **40 passed, 1 warning**. HTTP transport doubles are isolated contract tests, not evidence of a real Supabase request.
- Full provider-free suite: **1,335 passed, 4 skipped, 30 warnings**, 284.73 seconds, exit 0. Ruff and diff whitespace checks passed.
- Real ContentStore batch: **10 documents / 97 passages**. Actual PostgreSQL via PGlite loaded this batch and its original document bodies. Verified invisible-before-publish, invalid offset rejection, unchanged active state after failure, matching coverage, phrase query and type filter. The broad header query returned 41 passages; this is integration proof, not a legal relevance benchmark.
- Supabase migration, upload, publication and online search acceptance: **NOT RUN**. No SQL/admin connection is configured; the endpoint previously returned NXDOMAIN at two resolvers. Runtime flag remains off. No production body-index readiness claim.

## Logfire production change

The user explicitly confirmed the pending credential change. Updated only `LOGFIRE_TOKEN` in Vercel Production using stdin, stored as a Secret; no key is written to reports. Redeployment `dpl_BjUPSNgGo85erbcdPSMP8xacBEkB` became Ready. Two real requests to the canonical app were read back from logs for this exact deployment: homepage 200, search 503; neither log record contained Logfire 401/invalid-token. This is bounded observation, not proof that every future export succeeds. The new key's direct US `/v1/traces` HTTP 200 is documented in the prior full-text report. Search remains blocked separately by Supabase.

## Exact verification commands

```powershell
.venv/Scripts/python.exe -m pytest tests/services/test_remote_body_search.py tests/ingestion/test_body_remote.py tests/services/test_body_search.py tests/services/test_legal_browser.py tests/test_legal_routes.py -q
.venv/Scripts/python.exe -m pytest -q --junitxml=tmp/continuation-20260919/full.xml
.venv/Scripts/python.exe -m app.ingestion.body_remote prepare --store data/v3/content_store.sqlite3 --output tmp/continuation-20260919/real-body-batch --limit 10
node tests/sql/body_search_batch.mjs tmp/body-search-20260919/pg tmp/continuation-20260919/real-body-batch
```

The SQL harness additionally reads `source-documents.json` exported directly from ContentStore for the IDs in the prepared batch. Full bodies stay in ignored tmp, not in published artifacts. The script is retained under `tests/sql/`; PGlite 0.5.8 is installed in the ignored dependency folder documented by the prior report.

## Online rollout, pending actual access

1. Restore/verify the configured Supabase project endpoint and obtain a SQL connection with DDL rights. Check database capacity before loading passages. Do not delete the current corpus or vector collections.
2. Apply `migrations/20260919_legal_body_search.sql` once. Confirm `unaccent` is installed in schema `extensions`, RLS and grants match the checked contract. This creates new objects only.
3. Prepare a bounded bundle from documents matching the remote store. The source hash must match the remote document; otherwise publication fails and the previous active batch remains unchanged.
4. Stage with `.venv/Scripts/python.exe -m app.ingestion.body_remote upload --bundle <new-bundle>`. Use `--resume` only for the same bundle after an interrupted upload. Add `--publish` only when ready to atomically activate it. This requires the configured service-role key; never put credentials in CLI arguments.
5. Verify RPC coverage and phrase/filter/anchor cases against actual remote bodies before enabling `SUPABASE_BODY_SEARCH_ENABLED=true` and redeploying. Re-run public UI acceptance. None of these remote steps is claimed executed here.

Legal-effect registry and answer factual completeness remain separate unfinished requirements. This report does not promote metadata into verified current law.
