# AGENT_WORKFLOW.md — Mandatory Workflow Rules for AI Coding Agents

## Workflow Principles

1. **Audit Before Edit**: Inspect current runtime code, configuration, and tests before modifying logic.
2. **Deterministic Baseline First**: Establish verified code-based evaluation metrics before changing models or settings.
3. **No Fabricated Output**: Report exact empirical results or state `NOT RUN` / `BLOCKED`.
4. **Clean Decoupling**: Separate Stage A online pipeline execution from Stage B offline deterministic evaluation. Release online semaphores before running evaluation metrics.
5. **Explicit Destructive Authority**: Delete/recreate/reingest operations require
   explicit authorization for the exact index/collection and operation; normal
   implementation or evaluation work does not imply that authority.

## Execution Checkpoints

- **Pre-Flight**: Inspect source, affected tests, Git status, and the smallest
  focused command that proves the contract. Do not run a paid/live provider as
  an implicit baseline.
- **Implementation**: For behavior changes, observe focused RED before the
  smallest root-cause edit. Documentation-only changes use source/artifact
  comparison and link/contract checks instead of artificial code tests.
- **Verification**: While findings remain, run focused invalidated gates. Review
  the stable diff, then run the broader/full provider-free suite once when the
  change risk requires it.
- **Report & Manifest**: Generate immutable run artifacts under
  `docs/evaluation/runs/<run-id>/` only after source/configuration is stable.
  Any later source/config edit invalidates the artifact evidence.
