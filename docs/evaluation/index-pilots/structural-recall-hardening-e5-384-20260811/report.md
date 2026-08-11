# Qdrant structural pilot plan

- Run ID: `structural-recall-hardening-e5-384-20260811`
- Dataset: `vohuutridung/vietnamese-legal-documents@4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
- Documents: 827
- Structural records: 134334
- Source state SHA-256: `9c8c9b4d03cc7c9b3b0d390b40de8caed4a6d33d57d05267c653daa132a82b7c`
- Plan SHA-256: `aed21e97b1cf1759d1986bbe1a80ef2d0a6569d66d59d6fe432d0d091083723b`
- Capacity status: `PASS_CAPACITY`
- Capacity method: `explicit_conservative_v1`
- Projected bytes: 788245049
- Available bytes: 4291557760
- Provider calls: 0

Sparse, HNSW, WAL, and safety values are conservative estimates; post-finalize provider measurement is still required.

## Model probe outcome

- Acceptance: `BLOCKED_TECHNICAL` (not a retrieval-quality result)
- Dense model: `intfloat/multilingual-e5-small` (384 dimensions)
- Sparse model: `qdrant/bm25`
- Root cause: Qdrant reported positive inference usage only for the metered dense model. The client contract incorrectly required a second token-usage entry for cluster-native `qdrant/bm25` and raised `model_usage_mismatch` after the first acknowledged upsert.
- Remote effect: the failed probe wrote 64 canary points before validation raised. Those 64 points and one diagnostic point were deleted by exact ID; the collection was rechecked at 0 points.
- Recall values in `model-probe.json` are placeholders produced by the blocked path and must not be interpreted as measured zero recall.
- Bulk upload: `NOT RUN`
- Pinecone: unchanged
