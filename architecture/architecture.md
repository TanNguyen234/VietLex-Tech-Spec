# VietLex architecture compatibility entry

Status: compatibility path only. Updated 2026-09-01.

The technical source of truth is
[`docs/CURRENT_ARCHITECTURE.md`](../docs/CURRENT_ARCHITECTURE.md). Historical
plans under `docs/superpowers/` and evaluation artifacts describe the contract
that existed when they were created; they do not override current code/tests.

## Current runtime selector

```text
USE_LEGACY_FREE_PIPELINE=false (default)
  -> Vertex gemini-embedding-2, 1024d
  -> Qdrant vietlex-legal-rag-v3-vertex-1024
  -> dense + sparse IDF, raw RRF
  -> up to 3 payload evidence points / 720 context tokens

USE_LEGACY_FREE_PIPELINE=true
  -> Qdrant E5-small query inference, 384d
  -> Pinecone vietlex-legal-rag-v1 + local title/number FTS
  -> local structural chunking, Qdrant ColBERT with Pinecone BGE fallback
  -> Google Cloud blocked before client creation
```

The default Qdrant v3 collection was audited at 51,801 points over exactly
4,969 unique document IDs. It is a bounded slice, not the pinned 518,255-
document corpus. Pinecone v1 remains the explicit full-corpus legacy/free path;
there is no silent cross-fallback between these two contracts.

## Deployment boundary

`SERVERLESS_ONLINE_ONLY=true` runs `app/server.py` as direct FastAPI/Jinja SSR
on Vercel and reads chat evidence from Qdrant payloads. It does not package the
local SQLite corpus, so `/search` and `/documents/{id}` are outside that
deployment contract. `SERVERLESS_ONLINE_ONLY=false` retains the persistent-host
topology with local content and FTS stores.
