# VietLex Lean Remediation Implementation Plan

> **For agentic workers:** Execute inline with the repository's lean workflow. No subagent, commit, push, live-provider call, migration, deletion, or artifact promotion is authorized.

**Goal:** Make the Codex project open reliably, stop the apparent fallback to Light reasoning, verify the supplied audit, and fix only confirmed blockers needed for an intern/fresher-grade runnable project.

**Architecture:** Preserve the pinned RAG architecture and all persistent stores. First repair the project-local Codex configuration, then establish a single deterministic evaluation default over the committed curated dataset and promoted V5 gold release. Apply only small source-side corrections supported by a focused failing test.

**Tech Stack:** Codex CLI 0.149.0-alpha.4.1, TOML, Python 3.10+, pytest, FastAPI/Pydantic.

**Spec:** `C:\Users\VI TINH THANH AN\.codex\attachments\734a701a-4ef8-43fd-aed9-5387333e57aa\pasted-text.txt`

## Global Constraints

- Keep Pinecone v1, E5-small 384d, Qdrant staging/opt-in structural behavior, and provider boundaries unchanged.
- Preserve every pre-existing untracked evaluation artifact.
- Do not run paid/live providers, remote writes, ingestion, reindexing, migrations, deletions, commits, or pushes.
- Prefer one root-cause edit per confirmed behavior and one focused regression test; run the broad suite once after the diff is stable.
- Report live/cloud behavior as `NOT RUN` unless directly observed.

## Authority Ledger

| Deliverable | Allowed mutations | Forbidden mutations | Proof |
|---|---|---|---|
| Codex project startup | `.codex/config.toml` | global credentials, app state deletion | local `debug prompt-input` RED/GREEN probe |
| Audit verification | read-only source/tests/artifacts | provider calls, benchmark promotion | exact paths, hashes, focused commands |
| Lean remediation | confirmed source, dependency, tests, current docs | architecture migration, feature expansion | focused pytest then one broad suite |
| Final report | `outputs/` in the task workspace if needed | overwrite repository run artifacts | Git diff/status and command receipts |

## Boundary / Invariant Matrix

| Boundary | Invariant |
|---|---|
| Identity | Curated 420-case dataset and exact promoted gold release remain explicit. |
| Hashes | Existing dataset/sidecar SHA validation must not be weakened. |
| Indexing | No Pinecone/Qdrant schema, model, vector, or data mutation. |
| Provenance | Preserve dirty/untracked user artifacts and distinguish source changes from evidence. |
| Failures | Configuration and evaluation drift fail clearly; no silent provider switching is added. |
| Human/remote | Human gold promotion and every live-provider operation remain outside this task. |

---

### Task 1: Codex project configuration

**Files:**
- Modify: `.codex/config.toml`

**Contract:** Every `skills.config.path` is an absolute path to a folder containing `SKILL.md`; project model remains `gpt-5.6-sol` and reasoning does not drop below the global `high` setting.

- [x] Reproduce with `codex -C D:\Download\ProfessionalLegalRAG debug prompt-input "config probe"` and observe `AbsolutePathBuf deserialized without a base path`.
- [ ] Replace the 21 relative skill paths with resolved absolute Windows paths and align reasoning effort to `high`.
- [ ] Re-run the same probe and require exit 0, zero absolute-path errors, and the expected model/effort in rendered context.

### Task 2: Verify the supplied audit

**Files:**
- Inspect: `run_retrieval_eval.py`, `run_answer_eval.py`, `run_eval_suite.py`, `requirements.txt`, `.env.example`, `app/api/routes.py`, `app/main.py`, `app/config.py`, promoted V5 artifacts, and focused tests.

- [ ] Confirm or reject each P0/P1 claim using current source and committed artifacts.
- [ ] Record stale claims separately from confirmed blockers.
- [ ] Freeze the exact files/tests for Task 3; do not broaden into optional structural/provider experiments.

### Task 3: Minimal confirmed remediation

**Candidate files (only if claims remain confirmed):**
- Modify: `run_retrieval_eval.py`, `run_eval_suite.py`, `requirements.txt`, `.env.example`, `app/api/routes.py`.
- Test: `tests/evaluation/test_default_entrypoints.py` and the smallest affected API test module.

- [ ] Read `writing-good-tests.md`, add one focused failing regression per behavior, and observe the expected RED.
- [ ] Implement the smallest GREEN change: canonical committed dataset/current V5 defaults, direct dependency declaration, and safety ordering only where source proves the issue.
- [ ] Run only the affected focused tests while findings remain.

### Task 4: Stable review and verification

**Files:**
- Review: all tracked files changed by Tasks 1 and 3; compare with `git status` so untracked artifacts remain outside review.

- [ ] Run `git diff --check` and inspect the complete stable diff.
- [ ] Run Open Code Review delegation if the local `ocr delegate` workflow is callable; otherwise report it unavailable.
- [ ] Resolve important findings, then run the broad pytest suite once.
- [ ] Produce a corrected audit summary listing exact commands, pass/fail counts, `NOT RUN` boundaries, Git state, and remote effects.

