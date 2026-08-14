# P3 Pinecone structural replacement

## Frozen contract

- Purpose: recover production-scale structural retrieval after the verified Qdrant pilot became unreachable.
- Scope: all 827 pinned primary-legislation documents selected by the existing legal-type predicate, never a gold-document allowlist.
- Target: existing empty Pinecone index `llama-text-embed-v2-index`, namespace `national-primary-v2`.
- Model: Pinecone-hosted `llama-text-embed-v2`, 1024 dimensions, cosine, passage/query input types managed by the integrated index.
- Records: the existing deterministic 420-token/48-overlap structural chunks and exact provenance payload; inference text remains `vietlex-structural-document-v2`.
- Retrieval: semantic structural search plus exact document-number filtered search, deterministic fusion, per-document cap, and Pinecone `bge-reranker-v2-m3`.
- Isolation: do not delete or mutate `vietlex-legal-rag-v1`; do not change the production factory or default backend during P3.
- Durability: upload is resumable and idempotent; checkpoint identities bind record ID, chunk hash, inference-text hash, dataset revision, target index/namespace, and corpus manifest.
- Verification: remote count must equal 134,334 and deterministic sampled records must round-trip exact identity/provenance before benchmarking.
- Acceptance: fused Document Recall@24 `1.0`; Article Recall@24 `>=0.95`; Clause Recall@24 `>=0.90`; all-required coverage `>=0.95`; zero no-candidate/retrieval/reranker technical errors. Independent canary Document Recall@10 remains `>=0.90`.

## Execution

1. TDD the Pinecone index contract, record mapping, resumable upload, strict response parsing, and dense/exact retrieval.
2. Review the stable diff, run the affected matrix, then the full suite once.
3. Commit and push clean source without `.codex/config.toml`.
4. Generate immutable local plan; upload/resume the isolated namespace; verify count and sampled hashes.
5. Run the 40-case deterministic P3 benchmark and the independent canary check.
6. If a gate fails, diagnose the first stage loss and make only a corpus-wide/config-level correction on byte-identical inputs. Do not patch individual documents or cases.
7. Record final evidence in `docs/evaluation/CURRENT_STATUS.md`. P4 remains blocked until P3 passes.
