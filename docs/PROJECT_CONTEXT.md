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
- **Reranker**: Primary Qdrant ColBERT (`answerdotai/answerai-colbert-small-v1`) with fallback to Pinecone `bge-reranker-v2-m3`.

## Evaluation Integrity Policy

- Deterministic code metrics are primary.
- Ragas LLM judge calls are optional and disabled by default.
- Stage-level candidate survival must be tracked continuously across all 8 retrieval pipeline stages.
- Benchmark runs from uncommitted git trees must be recorded with `git_dirty=true` and a git diff SHA-256 hash.

## Opt-in Qdrant structural pilot

- A guarded v2 pilot is code-prepared for the 827 primary-legislation documents in the pinned 518,255-document corpus. Its immutable structural contract contains 134,334 article/clause records at 420/48 chunking.
- The pilot uses Qdrant Cloud Inference only: `Qwen/Qwen3-Embedding-0.6B` dense vectors at 1024 dimensions plus corpus-level `qdrant/bm25`. There is no local embedding fallback.
- Dense and BM25 document inputs use version `vietlex-structural-document-v2`: title, document number, legal type, structural path, citation, and unchanged evidence body. Payload/readback/checkpoints bind the exact inference-text SHA-256.
- The bounded model probe contains all 1,748 verified relevant rows plus one deterministic real row from each of the other 825 documents and 64 corpus title canaries. Golden labels never select corpus membership.
- The default probe performs no Pinecone inference. An immutable reference artifact is optional and cannot relax the absolute Qdrant gates.
- `audit` and `plan` are provider-free. `create`, `probe-model`, `upload`, `finalize`, `verify`, and `benchmark` are separate fail-closed remote phases and are not evidence of success until their immutable artifacts exist.
- The structural retriever and benchmark are opt-in. Pinecone `vietlex-legal-rag-v1` remains the production retrieval path; no cutover is authorized by local code completion.
