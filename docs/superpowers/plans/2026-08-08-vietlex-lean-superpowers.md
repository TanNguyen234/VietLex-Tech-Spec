# VietLex Lean Superpowers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-local workflow that reduces context, narration, and repeated verification while preserving VietLex safety, TDD, review, and evidence requirements.

**Architecture:** A small wrapper skill composes existing Caveman, Ponytail, CRG, and Superpowers workflows without modifying plugin caches. Static tests enforce its trigger, size, authority boundary, CRG source-validation rule, and verification cadence; pressure scenarios compare behavior before and after loading it.

**Tech Stack:** Markdown skill, JSON eval cases, pytest, CRG MCP, Git.

## Global Constraints

- `AGENTS.md` and task-specific skills remain authoritative.
- CRG narrows context but never replaces source validation.
- Ponytail may reduce scope and implementation size, never safety, error handling, TDD, review, or evidence.
- Caveman compresses communication, never technical content.
- Commit and local merge are authorized; push, destructive corpus operations, migrations, ingestion, and evidence promotion are not.

---

### Task 1: Lock the lean-workflow contract

**Files:**
- Create: `.agents/skills/vietlex-lean-superpowers/evals/evals.json`
- Create: `tests/skills/test_vietlex_lean_superpowers.py`

**Interfaces:**
- Consumes: project `AGENTS.md`, existing skill names, user authority boundary.
- Produces: pressure prompts and deterministic assertions for `SKILL.md`.

- [ ] **Step 1: Save two combined-pressure scenarios**

Cover P1 continuation and a cross-cutting evaluation bug. Each scenario combines time/token pressure, quality pressure, and an authority trap.

- [ ] **Step 2: Write the failing static test**

Assert that the skill exists, has trigger-only frontmatter, stays below 320 words, requires CRG-first/source validation, preserves TDD/review/verification, and distinguishes local merge from push/destructive work.

- [ ] **Step 3: Run the test to verify RED**

Run: `python -m pytest tests/skills/test_vietlex_lean_superpowers.py -q`

Expected: FAIL because `.agents/skills/vietlex-lean-superpowers/SKILL.md` does not exist.

- [ ] **Step 4: Run baseline pressure scenarios without the new skill**

Use fresh subagents in read-only mode. Record whether each response limits exploration, preserves the authority boundary, avoids redundant full-suite runs, and stays concise.

### Task 2: Implement the project-local lean skill

**Files:**
- Create: `.agents/skills/vietlex-lean-superpowers/SKILL.md`
- Modify: `tests/skills/test_vietlex_lean_superpowers.py` only if an assertion is proven ambiguous.

**Interfaces:**
- Consumes: `superpowers:*`, `caveman`, `ponytail`, and `codex-research-automation:crg-code-review`.
- Produces: an ordered decision protocol and a compact reporting contract.

- [ ] **Step 1: Write the minimal skill**

The sequence is: authority ledger; applicable task skills; CRG minimal context and one directed query; source validation; Ponytail minimal change; TDD; focused-to-broad verification; CRG change review; concise evidence report.

- [ ] **Step 2: Run the static test to verify GREEN**

Run: `python -m pytest tests/skills/test_vietlex_lean_superpowers.py -q`

Expected: PASS.

- [ ] **Step 3: Run the same pressure scenarios with the skill**

Expected: both satisfy all critical criteria; neither asks for already-granted permission; neither treats commit permission as push/destructive authorization.

- [ ] **Step 4: Refactor only if a pressure failure identifies a loophole**

Add the smallest general rule that closes the observed loophole, then rerun the failed scenario and static test.

### Task 3: Review, verify, and integrate P0 plus the lean workflow

**Files:**
- Review: all tracked P0 changes plus `.agents/skills/vietlex-lean-superpowers/`, `tests/skills/`, and this plan.
- Exclude: generated `docs/evaluation/preflight/p0-*` directories unless exact artifact preservation is separately authorized.

**Interfaces:**
- Consumes: a stable source tree and current P0 verification evidence.
- Produces: reviewed commits merged into local `main`.

- [ ] **Step 1: Update CRG and detect changed-code risk**

Run incremental graph update, then `detect_changes` with minimal detail. Validate every actionable finding against source.

- [ ] **Step 2: Run verification once on the stable tree**

Run the focused skill test, focused evaluation suites, full pytest suite, Ruff, compilation, and `git diff --check`. Record exact output; do not rerun a passed full suite unless source changes afterward.

- [ ] **Step 3: Stage only reviewed source, tests, docs, and skill files**

Run: `git diff --cached --check`

Expected: exit 0.

- [ ] **Step 4: Commit and merge locally**

Create an intentional commit on `codex/evaluation-trust-foundation`, switch to `main`, and merge without pushing.

## Self-Review

- Spec coverage: token economy, CRG, Caveman, Ponytail, quality gates, authority, pressure tests, review, and integration are covered.
- Placeholder scan: no `TBD`, `TODO`, or deferred implementation step remains.
- Type consistency: the only produced interface is the project-local `SKILL.md`; tests target that exact path.
