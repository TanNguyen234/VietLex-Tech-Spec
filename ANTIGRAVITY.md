# ANTIGRAVITY.md — Agent Workspace Rules & Entry Point

Welcome to the **VietLex Legal RAG** workspace (`TanNguyen234/VietLex-Tech-Spec`).

## Primary Directives

1. **Canonical Operations**: Read and obey root [`AGENTS.md`](AGENTS.md).
2. **Current Architecture**: Refer to [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md) as the technical source of truth.
3. **Project Context**: Refer to [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md).
4. **Agent Workflow**: Refer to [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md).

## Non-Negotiable Operational Principles

- **No Destructive Vector Operations**: Do not delete, recreate, migrate, or reingest Pinecone or Qdrant collections.
- **Evaluation First**: Deterministic code-based evaluation (`run_retrieval_eval.py`, `run_answer_eval.py`) is the default. Zero LLM judge calls during default runs.
- **Configuration vs Runtime**: Declaration in `app/config.py` does not prove runtime usage until verified in actual code flows.
- **Dirty Working-Tree Provenance**: Any evaluation run executed from a dirty working tree must be marked non-reproducible from Git commit SHA alone.
