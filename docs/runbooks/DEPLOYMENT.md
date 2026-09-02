# Deployment contract

Updated: 2026-09-02.

The active Vercel contract runs `app/server.py` directly as an online-only FastAPI/Jinja SSR function. Set `SERVERLESS_ONLINE_ONLY=true` and `USE_LEGACY_FREE_PIPELINE=false`; the function uses Qdrant v3 payload evidence for chat, Supabase for legal browsing, and never packages the local legal corpus. The verified public alias is <https://vietlex-legal-rag.vercel.app>.

The online-only function requires:

- Qdrant credentials for collection `vietlex-legal-rag-v3-vertex-1024`;
- Google Cloud project and ADC for v3 query embeddings and primary generation;
- an optional configured direct-API fallback for generation only;
- MongoDB for readiness, session/history, and interaction persistence;
- Supabase `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` for read-only legal
  search and document pages;
- a stable `WEB_SESSION_SECRET` and HTTPS `FRONTEND_URL`/`PUBLIC_BASE_URL`.

Local `CONTENT_STORE_PATH` and `LEGAL_FTS_PATH` are deliberately not required in
online-only mode. `/search` and `/documents/{id}` read the exact v3 document set
from Supabase under a read-only RLS policy. The persistent Docker topology still
requires its matching local stores. Never deploy `SUPABASE_SERVICE_ROLE_KEY` for
the read-only runtime; reserve it for explicit ingestion jobs.

Deploy in this order: configure MongoDB, Qdrant, Vertex, and Supabase read credentials in
Vercel; configure optional fallback credentials only when intentionally used;
deploy the FastAPI function; verify `/healthz`, `/readyz`, and `/`; then submit a
CSRF-protected bounded `/chat` request. Readiness checks configuration and
MongoDB without making paid provider calls.

The 2026-09-01 deployment passed health, readiness, SSR-root, and live chat smoke
checks. That proves the deployment contract, not whole-corpus coverage or legal
answer correctness. The separately executed Golden-50 artifacts are linked from
[`../evaluation/CURRENT_STATUS.md`](../evaluation/CURRENT_STATUS.md).

`USE_LEGACY_FREE_PIPELINE=false` selects Vertex/Qdrant v3 for production. The persistent Docker topology remains supported with `SERVERLESS_ONLINE_ONLY=false` and its matching SQLite stores. Production smoke checks include `/search` and one `/documents/{id}` response backed by Supabase.
