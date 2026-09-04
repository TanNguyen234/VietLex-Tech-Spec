# PROJECT_CONTEXT.md — VietLex Legal RAG System Context

## Project Overview

VietLex is an enterprise-grade Vietnamese legal Retrieval-Augmented Generation (RAG) system operating over a pinned third-party corpus of 518,255 legal documents (`vohuutridung/vietnamese-legal-documents`).

## Current Objective

The current priority is to establish a verified, measurable, reproducible, and deterministic evaluation framework before modifying core retrieval models or persistent vector indices.

## Latest verified state (2026-09-03)

- Direct FastAPI/Jinja SSR is deployed at
  <https://vietlex-legal-rag.vercel.app>. The 2026-09-02 browser smoke observed
  the SSR root, ready status, Supabase-backed search, and a full-document page.
  Direct `/healthz` was blocked by the browser client and is not claimed.
- The expanded Golden-50 v3 RRF+DBSF retrieval run completed 50/50 with zero
  retrieval/reranker technical errors and passed its gate: Document Recall@3
  `53/53`, Article Recall@3 `29/30`, Clause Recall@3 `13/14`, and all-required
  coverage `39/40` on the 40-case verified denominator.
- The answer run completed 50/50 generations and guardrail checks, but
  deterministic exact match was `0.0000` and token F1 `0.2305`. Opt-in Ragas
  covered 50/50 with no judge technical error; its means are secondary because
  generation and the observed judge both used Vertex `gemini-3.5-flash`.
- Final provider-free verification after the stable deployment source state was
  `925 passed, 2 skipped` with 10 deprecation warnings; two deployment tests
  timed out under the full-suite load and then passed when rerun independently.
- Both 2026-09-03 manifests record `git_dirty=true`, the exact Git diff hash,
  and provenance status `ok`. They do not demonstrate production readiness or
  whole-corpus legal accuracy.

## System Boundaries & Stores

- **Vercel online-only SSR:** `SERVERLESS_ONLINE_ONLY=true` runs the existing FastAPI/Jinja app directly on Vercel, omits local corpus files, uses Qdrant v3 payload evidence for chat, and uses Supabase for `/search` and `/documents/{id}`.

- **Runtime selector**: `USE_LEGACY_FREE_PIPELINE=false` (default) selects Vertex/Qdrant v3; `true` selects the Pinecone-v1 legacy/free path and blocks Google Cloud before client construction.
- **Durable full-corpus fallback**: Pinecone index `vietlex-legal-rag-v1` (namespace `legal-documents-v1`).
- **V3 primary collection**: Qdrant `vietlex-legal-rag-v3-vertex-1024`, 141,798 structural points over exactly 14,962 unique document IDs in the audited remote collection.
- **V3 local full-doc bundle**: `data/v3/content_store.sqlite3` and `data/v3/legal_fts.sqlite3` are the older 4,969-document slice and no longer match the expanded online set. V3 chat evidence itself comes from Qdrant point payload `body`.
- **Full-corpus local fallback store**: `data/huggingface/content_store.sqlite3` and `data/huggingface/legal_fts.sqlite3` remain the 518,255-document legacy/free stores.
- **Dense inference**: V3 uses Vertex `gemini-embedding-2` at 1024 dimensions. Legacy/free uses Qdrant Cloud staging `intfloat/multilingual-e5-small` at 384 dimensions.
- **Ranking/reranker**: V3 uses a 50/50 reciprocal-rank blend of Qdrant RRF and DBSF; Qdrant ColBERT remains rejected because it reduced verified article/clause recall. Legacy/free uses Qdrant ColBERT with Pinecone BGE fallback.
- **Supabase**: `public.legal_documents` contains the exact 14,962-document online v3 set. Online-only legal browsing uses a publishable-key read client under RLS; remote writes remain restricted to the server-only uploader.

## Evaluation Integrity Policy

- Deterministic code metrics are primary.
- Ragas LLM judge calls are optional and disabled by default.
- Stage-level candidate survival must be tracked continuously across all 8 retrieval pipeline stages.
- Benchmark runs from uncommitted git trees must be recorded with `git_dirty=true` and a git diff SHA-256 hash.

## Google Cloud model layer and free switch

- With `USE_LEGACY_FREE_PIPELINE=false`, production retrieval uses Vertex embeddings against Qdrant v3 and answer generation uses Vertex AI through ADC with `gemini-3.5-flash` as primary. Typed Vertex failures may use existing direct-API providers; runtime metadata preserves the actual provider/model and primary error kind.
- With `USE_LEGACY_FREE_PIPELINE=true`, Vertex retrieval, generation, rewrite, guardrails, migration helpers, and Vertex Ragas judge selection are disabled centrally before any Vertex client is created. Answer generation can still use configured OpenRouter, Gemini Direct API, NVIDIA, or Groq fallbacks; this means “no Google Cloud”, not guaranteed zero cost or unlimited quota.
- NeMo input/output guardrails use the same Vertex-primary adapter; legacy direct APIs remain secondary models. OmniGate is retained for evaluator use, not as the guardrail primary.
- Query rewriting is OFF by default and remains an explicit evaluation experiment.
- `gemini-embedding-2` supplies the 1024d query vectors for the v3 primary path. It is never used against the 384d Pinecone or Qdrant-v2 indexes.
- Evaluation may still select an explicit backend, but `--backend production` now records the boolean-selected effective backend. V3 failures are typed and never silently replace evidence with Pinecone results.
- Online `/chat` never runs Ragas. Optional offline Ragas uses Vertex AI first only when the boolean is `false`; free mode removes Vertex from the judge chain and uses configured direct APIs.

## Opt-in Qdrant structural pilot

- Collection `vietlex-legal-rag-v2-pilot-384` contains 134,334 structural records for 827 primary-legislation documents from the pinned 518,255-document corpus, at 420/48 chunking. It is not a full-corpus durable replacement for Pinecone.
- The live pilot contract uses Qdrant Cloud Inference with `intfloat/multilingual-e5-small` dense vectors at 384 dimensions plus `qdrant/bm25` sparse vectors with IDF. There is no local embedding fallback.
- Dense and BM25 document inputs use version `vietlex-structural-document-v2`: title, document number, legal type, structural path, citation, and unchanged evidence body. Payload/readback/checkpoints bind the exact inference-text SHA-256.
- The bounded model probe contains all 1,748 verified relevant rows plus one deterministic real row from each of the other 825 documents and 64 corpus title canaries. Golden labels never select corpus membership.
- The default probe performs no Pinecone inference. An immutable reference artifact is optional and cannot relax the absolute Qdrant gates.
- `audit` and `plan` are provider-free. `create`, `probe-model`, `upload`, `finalize`, `verify`, and `benchmark` are separate fail-closed remote phases and are not evidence of success until their immutable artifacts exist.
- `STRUCTURAL_BACKEND_ENABLED=true` runs this collection concurrently with the Pinecone-v1 + local-FTS full-corpus lane. Fusion removes only exact normalized chunk duplicates; distinct windows from the same Điều/Khoản remain eligible. The implemented Pinecone BGE cross-lane final rerank is separately gated by `CROSS_LANE_FINAL_RERANK_ENABLED` and remains off by default pending its required identical-input A/B. A final-reranker or lane failure with usable evidence is reported as `partial_retrieval_error`.
- Pinecone `vietlex-legal-rag-v1` remains the durable full-corpus store. The official curated-v5 gold corrects `case_323` to `59/2020/QH14`, Điều 123 khoản 4. The 827-document structural scope still prevents a standalone structural production-readiness claim; production claims require a reproducible combined-path benchmark.

## Grounded semantic cache

- Cache entries are valid only for the exact corpus and pipeline fingerprint (including `ANSWER_PROMPT_VERSION`) and only for request status `ok`.
- Each hit carries the original evidence contexts plus their SHA-256. Missing, empty, tampered, old-schema, `no_evidence`, or `blocked_output` entries are ignored.
