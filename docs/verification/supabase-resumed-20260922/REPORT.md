# Supabase resumed: production metadata search and reader — 22/09/2026

Scope: read-only verification after the project owner resumed Supabase project `jtldmpnghdzitvkbvald`. Runtime code was unchanged. Historical outage and recovery-UI evidence remains in [the earlier report](../legal-search-recovery-20260922/REPORT.md).

## Observed results

| Check | Result |
| --- | --- |
| Supabase REST, publishable key, exact `45/2019/QH14` | HTTP 200; document ID `333670` |
| Supabase REST, exact `68/2026/TT-BXD` | HTTP 200; no rows in the online set |
| Supabase `legal_documents` exact count | HTTP 206; `Content-Range: */14962` |
| Production Chrome `/search?q=45/2019/QH14` | HTTP 200; one result; selected as-of date preserved |
| Click result to `/documents/333670?as_of=2026-01-01` | HTTP 200; 238 rendered `.legal-section` elements |
| Production Chrome `/search?q=68/2026/TT-BXD` | HTTP 200; zero results; the workspace action prefills the query |
| Production `/legal-status` for the known number/date | HTTP 200; document number and date preserved; no published registry event observed |
| Production browser errors | No page error, failed request or HTTP error during the four Chrome checks; zero AI actions submitted |

[Supabase read-only JSON](supabase-resumed-readonly.json) · [Chrome JSON](production-resumed-browser.json) · [search](production-resumed-search-mobile.png) · [reader](production-resumed-reader-mobile.png) · [empty-state action](production-resumed-empty-action-mobile.png). Chrome used a 390×844 mobile viewport and the canonical `https://vietlex-legal-rag.vercel.app` domain. These checks prove only the named paths and documents; HTTP 200 and rendered sections do not establish legal correctness.

## Remaining boundary

`POST /rest/v1/rpc/legal_body_coverage` returned HTTP 404 `PGRST202`, meaning the named RPC was not in the exposed schema cache at verification time. Production `/search?...&scope=body` returned HTTP 503 with metadata-search recovery. `SUPABASE_BODY_SEARCH_ENABLED` remains false in code. The PostgreSQL body-search migration, body index import and cutover were **NOT RUN**; these mutate the remote database and need their own authorization and SQL/admin access. The current metadata/reader recovery does not provide article/body search online or expand the 14,962-document set. Registry has no published legal-effect event for the tested document; no validity conclusion was inferred.

The owner reported that the project had been paused and was resumed. [Supabase documentation](https://supabase.com/docs/guides/platform/free-project-pausing) says Free Plan projects can pause automatically after low database activity; the precise reason for this pause was **not verified** in owner email or Dashboard. The resumed REST and production responses establish current connectivity, not the historical trigger.

## Verification and effects

Commands run from `D:\Download\ProfessionalLegalRAG`:

```powershell
.venv\Scripts\python.exe tmp\continuation-20260922\supabase_resume_readonly.py
.venv\Scripts\python.exe tmp\continuation-20260922\production_recovery_browser.py
.venv\Scripts\python.exe scripts/check_repository_artifacts.py
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
```

The two read-only scripts wrote JSON/screenshots in ignored `tmp/continuation-20260922/`; the listed artifacts were copied here. Browser checks were real production integration checks. No unit tests or live AI-provider calls were run in this docs-only continuation. No SQL, ingestion, registry publishing, credentials, or environment variables were changed. Repository artifact and diff checks are recorded after documentation became stable; see Git history for the documentation commit. Unrelated pre-existing untracked files were left alone.
