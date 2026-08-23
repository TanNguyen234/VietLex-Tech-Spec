# Cross-lane final-rerank A/B — 2026-08-23

**Decision:** `KEEP_DISABLED`  
**Cutover:** `BLOCKED`  
**Clean source SHA:** `733f95baa2cb72090ed2e6ab8492ca5ca350baba`

Both arms used the same dataset/corpus revision, structural collection, profile,
rewrite mode, case order, Git SHA, and source-state hash. Configuration differed
only in `cross_lane_final_rerank_enabled`.

## Representative-10

| Metric | A: final rerank OFF | B: final rerank ON | Delta |
|---|---:|---:|---:|
| Document Recall@3 macro | 1.0000 | 1.0000 | 0.0000 |
| Article Recall@3 macro | 0.8571 | 0.9286 | +0.0715 |
| Clause Recall@3 macro | 0.7500 | 0.8750 | +0.1250 |
| All-required coverage | 0.9000 | 0.9000 | 0.0000 |
| No-candidate rate | 0.0000 | 0.0000 | 0.0000 |
| Retrieval technical-error rate | 0.0000 | 0.0000 | 0.0000 |
| Reranker technical-error rate | 0.0000 | 0.0000 | 0.0000 |
| Mean latency | 7.0355 s | 8.3060 s | +18.1% |
| p50 latency | 5.1155 s | 6.6749 s | +30.5% |
| p95 latency | 16.6846 s | 15.6846 s | -6.0% |

The observable merged lane-reranker output identities matched in `10/10`
cases. Gold matches at that pre-final proxy stage were identical at
`14 document / 8 article / 5 clause`. Final matches changed from `12/6/3` to
`14/7/4`. The quality signal is positive, but only one or two gold items moved
and all-required coverage did not improve, so the ten-case result was expanded.

## Verified-40 extension

| Metric | A: final rerank OFF | B: final rerank ON | Delta |
|---|---:|---:|---:|
| Document Recall@3 macro | 0.9250 | 0.9250 | 0.0000 |
| Article Recall@3 macro | 0.8704 | 0.9259 | +0.0555 |
| Clause Recall@3 macro | 0.7692 | 0.8846 | +0.1154 |
| All-required coverage | 0.8000 | 0.8500 | +0.0500 |
| No-candidate rate | 0.0000 | 0.0000 | 0.0000 |
| Retrieval technical-error rate | 0.0500 | 0.0000 | -0.0500 |
| Reranker technical-error rate | 0.0000 | 0.0000 | 0.0000 |
| Mean latency | 6.4553 s | 8.7399 s | +35.4% |
| p50 latency | 5.2357 s | 8.9153 s | +70.3% |
| p95 latency | 20.0716 s | 13.1543 s | -34.5% |

The 40-case quality result cannot authorize cutover. Observable merged
lane-reranker output identities matched only `25/40`; arm A also reported
partial retrieval errors for `case_061` and `case_065`. Therefore the apparent
quality/error/p95 gains are confounded by different upstream provider outcomes.

The evaluator currently persists merged lane traces, not the exact candidate
pool sent to the cross-lane final reranker. Consequently required-evidence
survival is reported using merged-reranker-output → final-evidence gold matches
as a proxy, not as proof of the exact final-reranker payload.

Provider call counts and cost were not persisted and are reported as `NOT
MEASURED`. Source inspection implies arm B adds at most one Pinecone final-rerank
call per eligible case, but no billing value is inferred.

No production configuration was changed. A valid cutover benchmark must capture
or replay one immutable cross-lane candidate pool for both policies.
