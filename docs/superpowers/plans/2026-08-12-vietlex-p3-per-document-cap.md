# P3 experiment: structural per-document candidate cap

## Decision

Change exactly one retrieval variable for the opt-in Qdrant structural pilot: `per_document_limit` from `4` to `8`. Do not change dense/BM25 top-k, RRF, fused limit, reranker input/return limits, reranker provider, final evidence limits, context budget, embeddings, vectors, or persistent data.

## Evidence and hypothesis

Baseline run: `docs/evaluation/runs/structural-e5-384-hybrid-parser-fix-20260812/`.

- Technically valid: 40/40 cases, no skips, no technical errors, no provenance drift.
- Baseline fused all-required coverage: `0.90`; required evidence survival: `49/53`.
- Deterministic replay of the recorded dense/BM25/exact candidates with only the cap changed to `8`: fused all-required coverage `0.95`; required evidence survival `51/53`.
- The replay is a hypothesis, not a live benchmark result.

## Protocol

1. Add a benchmark-only, explicitly recorded per-document-cap override. Keep the immutable index contract and evaluator source provenance separate.
2. TDD the override boundary: only this runtime field may differ; index/model/vector/chunk fields remain exactly bound to the verified plan.
3. Run focused tests, lint, compile, diff check, and the full suite.
4. Commit clean source, record its exact source-state SHA-256, then run one immutable 40-case benchmark with cap `8`.
5. Compare against the baseline using identical dataset, sidecar, case IDs, index, model, lane top-k, RRF, reranker configuration, metric version, and acceptance gates.

## Metrics and decision rule

- Primary: reranker-input/fused all-required coverage.
- Guardrails: required-evidence survival, Document/Article/Clause Recall, no-candidate rate, technical-error rates, provider/model identity, latency, and final all-required coverage.
- Accept cap `8` only if the primary metric improves without a required-level recall or technical-error regression.
- This experiment alone does not authorize production cutover. If source coverage improves but final coverage remains below gate, preserve the result and start a separate reranker experiment with byte-identical inputs.

## Remote and persistence boundary

The benchmark may perform Qdrant read/inference and the already configured remote reranker calls. It must not upsert/delete points, recreate collections, reindex, modify Pinecone, generate answers, call Ragas, or change production routing.
