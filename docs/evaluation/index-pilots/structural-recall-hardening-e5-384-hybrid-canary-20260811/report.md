# Qdrant structural pilot plan

- Run ID: `structural-recall-hardening-e5-384-hybrid-canary-20260811`
- Dataset: `vohuutridung/vietnamese-legal-documents@4d4e10b201544e8a4c49a1d3fa496595a7d486d0`
- Documents: 827
- Structural records: 134334
- Source state SHA-256: `fcd573edd55f8da6f9d8fb4f2d97faf13525740bdf9242e69fd3faaa3969f963`
- Plan SHA-256: `4792c97bfbbc317cfcfcffaa2a5a0aa5c1271c4766aedc182f7b8b0841b318e5`
- Capacity status: `PASS_CAPACITY`
- Capacity method: `explicit_conservative_v1`
- Projected bytes: 788245049
- Available bytes: 4291557760
- Provider calls: 0

Sparse, HNSW, WAL, and safety values are conservative estimates; post-finalize provider measurement is still required.

## Completed remote pilot

- Model probe: `PASS_MODEL_PROBE`
- Gold dense Document Recall@10: `1.0`
- Gold dense structural Recall@10: `0.975`
- Independent dense+BM25 RRF canary Document Recall@10: `1.0`
- Upload: `UPLOAD_COMPLETE`, 134,334/134,334 records
- Finalize: `PASS_FINALIZE`, HNSW `m=16`, collection green, optimizer ok
- Verify: `PASS_VERIFY`, exact count 134,334
- Deterministic samples: 18/18 payloads, 18/18 dense vectors, and 18/18 sparse vectors validated
- Remote cleanup calls: 0
- Production Pinecone and production routing: unchanged

The first benchmark was blocked because the opt-in structural backend flag was disabled. The enabled retry executed all 40 cases but was also `BLOCKED_TECHNICAL`: both dense and BM25 payload consumers rejected the intentionally persisted `inference_text_sha256` field as extra. These blocked artifacts are not retrieval-quality results and are retained under `docs/evaluation/runs/`.
