# VietLex Vertex/Qdrant v3 focused retrieval pilot

Run: `retrieval-vertex-v3-goldenfull-verified40-20260826`

This is a 40-case structural retrieval canary over 53 human-verified evidence labels. All verified labels come from two documents, so the run tests whether the v3 chunking/embedding lane can retrieve known legal structure; it does not establish broad production readiness.

## Result

| Lane | Doc recall @3 | Article recall @3 | Clause recall @3 | All-required @3 | Technical errors | P50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Vertex/Qdrant v3 raw RRF | 53/53 (100.0%) | 30/30 (100.0%) | 13/14 (92.9%) | 39/40 (97.5%) | 0/40 | 1.79 s |
| Vertex/Qdrant v3 + Qdrant ColBERT | 48/53 (90.6%) | 26/30 (86.7%) | 11/14 (78.6%) | 33/40 (82.5%) | 0/40 | 9.30 s |
| Historical Qdrant v2 comparator | 50/53 (94.3%) | 27/30 (90.0%) | 12/14 (85.7%) | 34/40 (85.0%) | 0/40 | 8.92 s |
| Vertex/Qdrant v3 + Pinecone BGE | NOT SCORED | NOT SCORED | NOT SCORED | NOT SCORED | 40/40 | 15.00 s |

The raw Vertex/Qdrant v3 retrieval is the strongest result in this focused canary. Qdrant ColBERT degrades all four quality measures and adds about 7.5 seconds at p50, so it should not be enabled for this lane without a new A/B justification. Pinecone BGE could not be evaluated because the organization has exhausted its 500-request monthly rerank limit; zeros from that attempt are technical failures, not quality scores.

## Root cause found

The original migration cap of 16 chunks per document was the dominant failure. Before full indexing of the two verified-gold documents, raw v3 produced document recall @24 of 36/53, article recall @3 of 2/30, clause recall @3 of 0/14, and all-required @3 of 3/40. After indexing all 1,768 structural chunks from those documents, raw all-required @3 rose to 39/40.

The 16-chunk evenly-spaced policy is therefore unsafe for long Vietnamese statutes when answer correctness is the production priority. A future 50,000-document migration needs a point budget based on retained legal structure, not a fixed per-document cap.

## Current remote and production state

- v3 collection: `vietlex-legal-rag-v3-vertex-1024`, 22,037 points, green.
- Initial balanced migration: 2,000 documents / 20,236 planned records; remote count after the run was 20,239 because three preflight points already existed outside the batch.
- Full golden-document fill: 1,766 new points; 2 checkpoint skips.
- Production routing changed: no.
- Pinecone and Qdrant v2 were not deleted or recreated.
- One known raw miss remains: `case_371_ctx02_cit01`.

## Decision

Do not cut over yet. Keep v3 isolated, remove the fixed 16-chunk assumption in the migration design, then run a broader representative pilot whose gold evidence spans many documents. For v3 ranking, retain raw hybrid/RRF as the current candidate; test a Google Cloud reranker only as a separate identical-input A/B with explicit model, quota, latency, and cost evidence.

## Evidence limits

The evaluator was executed inline and raw candidate payloads were not persisted. This directory preserves the measured numerators, denominators, case misses, provider errors, migration counts, and provenance. The Qdrant v2 row comes from `retrieval-crosslane-b-verified40-20260823`, an earlier immutable live run on the same selected case IDs, not a simultaneous rerun.
