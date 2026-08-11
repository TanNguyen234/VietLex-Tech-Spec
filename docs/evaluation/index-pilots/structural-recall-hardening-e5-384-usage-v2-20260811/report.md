# Qdrant structural pilot plan

- Run ID: `structural-recall-hardening-e5-384-usage-v2-20260811`
- Dataset: `vohuutridung/vietnamese-legal-documents@4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
- Documents: 827
- Structural records: 134334
- Source state SHA-256: `7f4751fa768589b7f9041a57a1116ba077ce6afa8d544c1d7ec45610bc1a6eab`
- Plan SHA-256: `7686b8ac0f4b84f0cbd5d36608ec035abf58623984824c18b98775f75512e14e`
- Capacity status: `PASS_CAPACITY`
- Capacity method: `explicit_conservative_v1`
- Projected bytes: 788245049
- Available bytes: 4291557760
- Provider calls: 0

Sparse, HNSW, WAL, and safety values are conservative estimates; post-finalize provider measurement is still required.

## Model probe outcome

- Acceptance: `FAIL_QUALITY`
- Technical errors: 0
- Probe records: 2,573 real structural rows; synthetic rows: 0
- Gold coverage: 40/40
- Gold Document Recall@1/@3/@10: `1.0`; MRR: `1.0`
- Gold structural Recall@1: `0.875`; Recall@3: `0.95`; Recall@10: `0.975`; MRR: `0.9104166667`
- Canary Document Recall@1: `0.578125`; Recall@3: `0.71875`; Recall@10: `0.8125`
- Failed gate: canary Document Recall@10 was below the declared `0.90` floor
- Dense provider usage: 874,259 E5-small tokens; BM25 is cluster-native and unmetered
- Vector readback: 2,573/2,573 passed
- Elapsed: 352.024 seconds
- Bulk upload/finalize/verify/benchmark: `NOT RUN`
- Production Pinecone: unchanged
- Cleanup: all 2,573 exact probe IDs were deleted after the artifact was persisted; isolated collection count returned to 0 and status remained green

The 40-case gold slice references only two corpus documents, so its perfect document recall does not demonstrate whole-scope recall. The independent 64-document canary is the relevant generalization warning.
