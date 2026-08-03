# AGENT_WORKFLOW.md — Mandatory Workflow Rules for AI Coding Agents

## Workflow Principles

1. **Audit Before Edit**: Inspect current runtime code, configuration, and tests before modifying logic.
2. **Deterministic Baseline First**: Establish verified code-based evaluation metrics before changing models or settings.
3. **No Fabricated Output**: Report exact empirical results or state `NOT RUN` / `BLOCKED`.
4. **Clean Decoupling**: Separate Stage A online pipeline execution from Stage B offline deterministic evaluation. Release online semaphores before running evaluation metrics.
5. **No Destructive Operations**: Never delete, recreate, or reingest Pinecone or Qdrant collections.

## Execution Checkpoints

- **Pre-Flight**: Run pytest suite to confirm clean baseline (`python -m pytest -q`).
- **Implementation**: Make logically isolated code edits.
- **Verification**: Run focused unit tests after every edit.
- **Report & Manifest**: Generate immutable run artifacts under `docs/evaluation/runs/<run-id>/`.
