---
name: vietlex-lean-superpowers
description: Use when VietLex work must reduce token use, repeated edits, tests, reviews, or agent coordination while preserving engineering and evidence quality.
---

# VietLex Lean Superpowers

`superpowers:using-git-worktrees` default: **OFF**. Reuse an existing worktree if active; do not create a worktree unless the user/task explicitly requests one. If requested, invoke it.

## Protocol

1. **Authority ledger:** deliverable | allowed mutations | forbidden mutations | proof. Commit/local merge authority does not authorize push, PR, ingestion, migration, deletion, provider calls, or evidence promotion.
2. **Reality Probe:** Invoke `codex-research-automation:crg-code-review`; call `mcp__crg__get_minimal_context_tool` first, then one directed `mcp__crg__query_graph_tool` per unresolved relationship. Source-validate. Inspect pinned artifact and edge strata before fixtures. Record a boundary/invariant matrix: identity, hashes, indexing, provenance, failures, human/remote boundary. Without CRG, use `rg` and bounded slices.
3. **Plan Freeze:** After probing, freeze files, contract, RED test, focused command, review target, and authority. Apply Ponytail's smallest root-cause solution after impact is known; never weaken validation, observability, security, or legal evidence rules.
4. **Focused TDD:** Behavior changes use `superpowers:test-driven-development`: RED, minimal GREEN, refactor. While findings remain, run only invalidated focused gates; isolate defects.
5. **Review-clean:** Reviewer inspects the Git range directly; review package only when repo access is unavailable. Review each task before commit, then final review the combined feature diff. For changed-code review call `mcp__crg__detect_changes_tool`. If the graph is stale, update only with mutation authority; on a read-only task, read-only fallback: use `rg`/source; do not update the graph. Resolve every unresolved Important finding; rerun invalidated focused gates.
6. **Stable verification:** After final review is review-clean, run broader/full once, including the full suite. If source changes after the full suite, rerun the full suite before integration plus invalidated gates. Never reuse stale evidence.
7. **Integrate/report:** One review-clean commit per task; do not commit each review round. Commit and local merge only when explicit current-task authority grants them; stage explicit paths. Target-branch integration follows stable verification. Report results, `NOT RUN`, limits, Git, and remote effects.

## Coordination budget

- Bounded work: Terra medium/high. High-risk/final review: Sol high. CRG risk may raise, never lower, rigor.
- Do not inspect shared diff/status while an agent runs. Wait for milestones; publish one changed-state update, not polling.
- Use Caveman-style updates at phase changes, failures, blockers, or waits over 60 seconds. Reopen source only for unresolved questions.

## Guardrail

Token pressure never weakens AGENTS.md, skills, TDD, review, verification, provenance, immutable artifacts, or human-only evidence promotion.
