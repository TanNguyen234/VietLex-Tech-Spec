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
