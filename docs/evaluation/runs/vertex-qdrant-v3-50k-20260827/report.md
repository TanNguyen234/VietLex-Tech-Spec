# Vertex/Qdrant v3 bounded 50k migration

Run date: `2026-08-27` (Asia/Bangkok)

Command:

```powershell
.venv\Scripts\python.exe -u run_vertex_qdrant_migration.py --max-documents 5000 --max-points 50000 --chunk-max-tokens 320 --chunk-overlap-tokens 32 --batch-size 16 --concurrency 8 --progress-every 50 --allow-remote-write
```

## Result

- Collection: `vietlex-legal-rag-v3-vertex-1024`
- Embedding: Google Vertex AI `gemini-embedding-2`, 1,024 dimensions
- Planned migration set: `50,000 / 50,000` records acknowledged
- This resume: `14,064` uploaded, `35,936` skipped from the acknowledgement ledger
- Remote collection after completion: `51,801` points, status `green`
- Production retrieval routing changed: `false`

The remote count is larger than the bounded 50,000-record plan because the collection already contained preflight and full golden-anchor records. This migration covers a balanced selection of 5,000 documents, not 50,000 documents and not the complete 518,255-document corpus.

## Decision boundary

The migration proves bounded upload, resumability, and remote collection health. It does not authorize a production cutover. The focused 40-case canary still favors raw hybrid/RRF over Qdrant ColBERT, and the 50-case `qdrant-only` runtime audit failed its quality gate.
