# VietLex Production Operations

Updated: 2026-09-03.

VietLex supports two explicit deployment topologies:

- direct Vercel FastAPI/Jinja SSR with `SERVERLESS_ONLINE_ONLY=true`, online
  MongoDB/Qdrant/Vertex/Supabase dependencies, and no packaged local corpus;
- a persistent FastAPI/Docker host with `SERVERLESS_ONLINE_ONLY=false` and the
  matching SQLite/Zstandard content and FTS stores.

Do not mix readiness expectations between the two. Vercel is the active public
SSR host, not only a proxy. Its legal-browser pages read Supabase; the persistent
topology reads matching local stores instead.

## Data classes

- MongoDB users, auth sessions, chat sessions, and interaction logs are source data. Use managed daily backups with retention matching the privacy policy.
- `content_store.sqlite3` is the pinned local legal-content source/cache. Copy it only from a stopped instance or a verified SQLite snapshot and retain its SHA-256.
- `legal_fts.sqlite3` is derived and rebuildable from the pinned content store and dataset revision.
- Pinecone vectors are derived from the pinned corpus and immutable ingestion manifests. Pinecone is not the backup for user or full-text data.
- Qdrant collections include active v3 runtime evidence, inference/rerank
  staging, and retained pilots. Never infer ownership or deletion safety from a
  low point count.

Current Qdrant ownership:

| Collection | Role | Deletion rule |
| :--- | :--- | :--- |
| `vietlex-embedding-staging` | E5 query inference staging | Active runtime dependency; never classify as garbage from point count alone. |
| `vietlex-rerank-staging` | ColBERT rerank staging | Active runtime dependency; zero points is normal after cleanup. |
| `vietlex-legal-rag-v2-pilot-384` | Existing 384d structural pilot | Retain until its evaluation history is formally retired. |
| `vietlex-legal-rag-v3-vertex-1024` | Active default v3 runtime; 141,798 points over 14,962 audited document IDs | Never delete/recreate without explicit authorization and a migration plan; it is not full-corpus coverage. |

Before deleting a Qdrant collection, verify its exact name, point count, aliases, current config references, runtime role, and checkpoint/report provenance. Deletion is irreversible and requires explicit authorization for the named collection.

## Incremental Vertex–Qdrant pilot

`run_vertex_qdrant_migration.py` is dry-run-first. Remote creation needs both `--allow-create` and `--allow-remote-write`; subsequent resumable batches need `--allow-remote-write`. Qdrant acknowledgements are stored in the configured SQLite checkpoint only after a successful upsert. Increase `--max-documents` and `--max-points` gradually and record the output hashes for each batch.

The pilot uses balanced legal types and an even structural sampling budget per long document. It is intentionally not a full-corpus ingestion command. Estimate dense bytes as `points × dimension × 4` before HNSW, sparse index, payload, replicas, and optimizer overhead; confirm actual cluster capacity before every material expansion.

## Backup check

1. Confirm the managed MongoDB backup completed and record its timestamp.
2. For persistent hosts, snapshot `content_store.sqlite3` on the persistent
   volume and verify SQLite integrity plus SHA-256. This step is not applicable
   to online-only Vercel functions because the corpus is not packaged there.
3. Retain the dataset revision, ingestion report, vector manifests, application Git SHA, and production environment-variable names without secret values.
4. Do not copy `.env`, service-account JSON, raw cookies, or account tokens into reports.

## Restore check

1. Restore MongoDB into an isolated database and verify required indexes and TTL policies.
2. For the persistent topology, restore `content_store.sqlite3` to an isolated
   volume and verify its stored build report and integrity.
3. Rebuild `legal_fts.sqlite3` from that content store when necessary; do not treat a stale FTS file as source data.
4. Point a non-public backend at the restored stores, set fresh secrets, and require `GET /healthz` plus `GET /readyz` to pass.
5. Run provider-free smoke tests first. Provider calls and vector writes require separate authorization.
6. For online-only Vercel, require health/readiness/root/chat plus Supabase-backed
   search and document-detail checks. For persistent hosts, run the same page
   checks against the local stores. Switch traffic only after the
   topology-specific checks pass.

## Minimum alerts

Monitor backend uptime, `/readyz`, request error rate, P95 chat latency, MongoDB
and Supabase availability, and provider failures. Add persistent-volume capacity for the
persistent topology and Vercel function duration/cold-start behavior for the
serverless topology. Never include legal queries, passwords, cookies, or tokens
in alert payloads.
