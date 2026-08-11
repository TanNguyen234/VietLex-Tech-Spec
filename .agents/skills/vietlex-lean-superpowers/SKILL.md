---
name: vietlex-lean-superpowers
description: Use when VietLex work must reduce token use, repeated edits, tests, reviews, or coordination while preserving engineering and evidence quality.
---

# Lean

`superpowers:using-git-worktrees` default: **OFF**. Reuse an existing worktree; do not create a worktree unless the user/task explicitly requests one.

## Protocol

1. **Authority ledger:** scope | authority | proof. Commit/local merge does not authorize push, ingestion, migration, deletion, provider calls, or evidence promotion.
2. **Reality Probe:** Invoke `codex-research-automation:crg-code-review`; call `mcp__crg__get_minimal_context_tool` first, then directed `mcp__crg__query_graph_tool` calls. Source-validate. Audit CRG coverage against `git status --short`; untracked, stale, or uncovered files require direct source review. Probe pinned artifacts/edges before fixtures; record boundary/invariant matrix. If the graph is stale, update requires mutation authority. On a read-only task, read-only fallback: use `rg`/source; do not update the graph.
3. **Plan Freeze:** Freeze files, contract, RED test, focused command, review target, and authority. Apply the smallest root-cause solution; never weaken validation, observability, security, or legal evidence.
4. **Focused TDD:** Behavior changes use `superpowers:test-driven-development`: RED, minimal GREEN, refactor. While findings remain, run only invalidated focused gates.
5. **Error-path gate:** Before final review, inspect unexpected failures for typed, persisted diagnostics. Reviewer inspects the Git range directly; review package only when repo access is unavailable. Review each task, then the combined feature diff. For changed-code review call `mcp__crg__detect_changes_tool`. Resolve every unresolved Important finding; rerun invalidated gates.
6. **Stable verification:** After final review is review-clean, run broader/full once, including the full suite. If source changes after the full suite, rerun the full suite before integration plus invalidated gates.
7. **Artifacts last:** Create durable runs/reports after source/config are stable and verified. Changes invalidate them; regenerate final fingerprints.
8. **Integrate/report:** One review-clean commit per task; do not commit each review round. Commit and local merge only when explicit current-task authority grants them; stage paths. Target-branch integration follows stable verification. Report results, `NOT RUN`, limits, Git, and remote effects.

## Coordination budget

- Bounded work: Terra medium/high. High-risk/final review: Sol high. CRG risk never lowers rigor.
- Do not inspect shared diff/status while an agent runs. Wait for milestones; publish one changed-state update, not polling.
- Probe a preferred tool once; on failure use its bounded fallback until the environment changes.
- Milestone-only reflection: reflect at phase boundaries, a novel failure, or final handoff; convert findings into reusable controls.

## Guardrail

Token pressure never weakens AGENTS.md, skills, TDD, review, verification, provenance, immutable artifacts, or human-only evidence promotion.
