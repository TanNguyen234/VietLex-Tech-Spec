# Structural reranker A/B — cap 8

The A/B is valid: all 40 `body_v1` reranker inputs have byte-identical query/document SHA-256 values across the two runs. Both runs used the same source state, collection, selected cases, retrieval limits, candidate cap, metric version, and final selector. Both completed 40/40 cases with zero technical errors.

| Metric | Qdrant ColBERT | Pinecone BGE | BGE delta |
|---|---:|---:|---:|
| Final all-required coverage | 0.725 | 0.850 | +0.125 |
| Reranker-output document recall | 0.9057 | 1.0000 | +0.0943 |
| Reranker-output article recall | 0.8667 | 0.9333 | +0.0666 |
| Reranker-output clause recall | 0.7857 | 0.8571 | +0.0714 |
| Mean total latency (seconds) | 4.099180 | 1.712522 | -2.386658 |

Observed providers were exactly Qdrant `answerdotai/answerai-colbert-small-v1` for 40 cases and Pinecone `bge-reranker-v2-m3` for 40 cases. No fallback was inferred from configuration alone.

Decision: select Pinecone BGE for the next isolated P3 experiment. Do not cut over production. Candidate input remains the bottleneck: Article Recall is `0.9333`, Clause Recall is `0.8571`, and final all-required coverage remains below the `0.95` gate.
