# PROJECT_CONTEXT.md — VietLex Legal RAG System Context

## Project Overview

VietLex is an enterprise-grade Vietnamese legal Retrieval-Augmented Generation (RAG) system operating over a pinned third-party corpus of 518,255 legal documents (`vohuutridung/vietnamese-legal-documents`).

## Current Objective

The current priority is to establish a verified, measurable, reproducible, and deterministic evaluation framework before modifying core retrieval models or persistent vector indices.

## System Boundaries & Stores

- **Durable Vector Storage**: Pinecone index `vietlex-legal-rag-v1` (namespace `legal-documents-v1`).
- **Local Content Store**: SQLite + compressed Zstandard full document store (`data/huggingface/content_store.sqlite3`).
- **Dense Inference**: Qdrant Cloud staging (`intfloat/multilingual-e5-small`, 384 dimensions).
- **Lexical Search**: Local SQLite FTS index for document numbers and titles (`data/huggingface/legal_fts.sqlite3`).
- **Reranker**: Pinecone v1 uses Qdrant ColBERT with Pinecone BGE fallback. The opt-in structural path uses Pinecone `bge-reranker-v2-m3` by default after an identical-input representative-10 A/B; Qdrant ColBERT remains an available secondary mode.

## Evaluation Integrity Policy

- Deterministic code metrics are primary.
- Ragas LLM judge calls are optional and disabled by default.
- Stage-level candidate survival must be tracked continuously across all 8 retrieval pipeline stages.
- Benchmark runs from uncommitted git trees must be recorded with `git_dirty=true` and a git diff SHA-256 hash.

## Google Cloud model layer (Phase G0)

- Production answer generation uses Google Cloud Vertex AI through ADC with `gemini-3.5-flash` as primary. Typed Vertex failures may use the existing OpenRouter, Gemini Direct API, NVIDIA, and Groq models as secondary providers; runtime metadata must preserve the actual provider/model and primary error kind.
- NeMo input/output guardrails use the same Vertex-primary adapter; legacy direct APIs remain secondary models. OmniGate is retained for evaluator use, not as the guardrail primary.
- Query rewriting is OFF by default and remains an explicit evaluation experiment.
- `gemini-embedding-2` is integrated only for isolated 384/768/1024 probes. Production dense retrieval remains E5-small 384d.
- Online `/chat` never runs Ragas. Optional offline Ragas uses Vertex AI `gemini-3.5-flash` through ADC as its primary judge; legacy APIs remain best-effort fallbacks.

## Opt-in Qdrant structural pilot

- Collection `vietlex-legal-rag-v2-pilot-384` contains 134,334 structural records for 827 primary-legislation documents from the pinned 518,255-document corpus, at 420/48 chunking. It is not a full-corpus durable replacement for Pinecone.
- The live pilot contract uses Qdrant Cloud Inference with `intfloat/multilingual-e5-small` dense vectors at 384 dimensions plus `qdrant/bm25` sparse vectors with IDF. There is no local embedding fallback.
- Dense and BM25 document inputs use version `vietlex-structural-document-v2`: title, document number, legal type, structural path, citation, and unchanged evidence body. Payload/readback/checkpoints bind the exact inference-text SHA-256.
- The bounded model probe contains all 1,748 verified relevant rows plus one deterministic real row from each of the other 825 documents and 64 corpus title canaries. Golden labels never select corpus membership.
- The default probe performs no Pinecone inference. An immutable reference artifact is optional and cannot relax the absolute Qdrant gates.
- `audit` and `plan` are provider-free. `create`, `probe-model`, `upload`, `finalize`, `verify`, and `benchmark` are separate fail-closed remote phases and are not evidence of success until their immutable artifacts exist.
- `STRUCTURAL_BACKEND_ENABLED=true` makes this collection the primary runtime and evaluation retrieval path. A technical failure or no-candidate result falls back observably to Pinecone v1; the fallback is never reported as an unqualified success.
- Pinecone `vietlex-legal-rag-v1` remains the durable full-corpus store. The structural collection's limited scope and the unresolved `case_323` gold-label defect prevent a production-ready claim or a full verified benchmark promotion.
