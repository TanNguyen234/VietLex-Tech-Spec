# VietLex Verified Gold Adjudication Design

**Date:** 2026-08-08

**Phase:** P1 — Verified Gold Adjudication
**Status:** Approved for automatic local implementation by the user's current-task authorization

## Problem

The pinned 420-case dataset has 245 answerable cases and 483 evidence labels, but the current sidecar has zero `verified` evidence. Deterministic candidate discovery is useful, but it cannot establish legal correctness or authorize evidence promotion. P2 therefore remains blocked until a human-reviewed, versioned sidecar exists.

The local corpus is available through a read-only 518,255-document SQLite/Zstandard content store and a title/document-number FTS index. The FTS index is not body/article search. Candidate generation must remain honest about this boundary.

## Goals

- Produce an immutable, deterministic queue covering 30–50 answerable cases; default 40.
- Stratify by question type and required evidence level before corpus lookup.
- Record hashes, parsed citations, candidate identities, structural locators, anchor diagnostics, corpus revision, source provenance, and a pending human-decision contract.
- Preserve every resolved human decision, including negative outcomes.
- Preview exact sidecar changes before promotion.
- Require a human-populated decision artifact and explicit approval of the preview hash before writing a new sidecar.
- Never overwrite the current sidecar or another adjudication artifact.

## Non-goals

- No provider calls, Ragas, generation, live retrieval benchmark, ingestion, reindexing, vector changes, or corpus mutation.
- No automatic conversion of deterministic matches into `verified` evidence.
- No claim that title FTS provides article/body retrieval.
- No P2 execution before an approved promoted sidecar satisfies the P1 exit gate.

## Chosen architecture

Use three immutable stages:

1. **Queue:** deterministic case selection and read-only local candidate discovery write `queue.json`, `decision_template.json`, and `queue_summary.json` to a unique directory.
2. **Preview:** a separate human-filled decision artifact is validated against the queue file SHA-256. The preview records every proposed status/identity change, status counts, exact case-set validation, and the complete proposed sidecar, but does not write a sidecar.
3. **Promotion:** the command requires the exact preview SHA-256 previously shown to and approved by the user. It revalidates the queue, decisions, source sidecar, dataset case set, and preview before writing a new versioned sidecar plus audit summary.

The existing `audit_golden_dataset.py` remains a diagnostic/candidate source; it is not used as a promotion authority.

## Queue contract

The queue schema version is `1.0.0`. It contains:

- metadata: queue ID, UTC creation time, command, dataset/sidecar hashes, dataset and corpus revisions, Git SHA/dirty/diff/source-state provenance, target/selected case counts, candidate limit, selection seed, provider calls (`0`), and queue status;
- flat evidence rows: case/evidence IDs, question and type, reference answer/context SHA-256 hashes, context/citation indexes, required level, parsed citation units, candidate documents, and a pending decision object;
- candidates: stable candidate ID, rank, document ID/number/title/source URL/content hash, discovery method, document-anchor method/diagnostics, matched structural Article/Clause/citation/chunk hash, and whether the required level is structurally supported.

No raw reference answer or full reference context is persisted. The public legal source URL and content hashes support review without copying full corpus text into the audit artifact.

## Deterministic selection and candidate discovery

1. Exclude `unanswerable` cases from the queue.
2. Derive each case stratum from `(question_type, highest_required_level)` using the current sidecar.
3. Order cases within each stratum by `SHA-256(seed + case_id)` and round-robin sorted strata until the requested 30–50 target is reached.
4. Search only selected cases. Build one query per case from the question plus parsed document numbers. Use the existing title/document-number FTS with a default limit of 12.
5. Add any source-sidecar document ID first, deduplicate stably, and read candidate bodies with `ContentStore.get_many()` in read-only mode.
6. Evaluate reference-context anchors against each document. For matched documents, chunk by the existing legal structure and record the first matching structural chunk. Candidates without an anchor remain visible for a negative human decision.

If fewer than 30 answerable cases exist, persist an honest `BLOCKED` queue. Missing candidates never cause forced replacements or inferred verification.

## Human decision contract

Allowed decisions are `verified`, `rejected`, `corpus_missing`, `ambiguous`, and `insufficient_evidence`. `pending` is allowed only in the generated template.

Every resolved row requires:

- stable non-PII reviewer identity;
- timezone-aware UTC review timestamp;
- `high`, `medium`, or `low` confidence;
- notes for every negative or non-high-confidence decision;
- selected candidate ID for `verified`.

A verified decision must select a queue candidate with a resolved document identity and a matched document anchor. Article evidence additionally requires a matched Article; Clause evidence requires matched Article and Clause. Candidate hints cannot be substituted for structural matches.

## Preview and promotion

Preview requires a resolved decision for every queue row. It updates only the selected sidecar labels and preserves all other labels byte-semantically. Negative decisions map to explicit non-verified evidence statuses. Reviewer notes are stored as SHA-256 in the promoted sidecar; the decision artifact retains the review text.

Promotion is impossible without all of:

- queue file SHA matching the decision artifact;
- source sidecar SHA matching the preview;
- exact dataset/sidecar case-set validation;
- all verified structural gates passing;
- a preview payload SHA matching `--approve-preview-sha256`;
- a new output directory.

The agent must still receive explicit user approval of that preview hash in the promotion task. General commit/merge authorization does not satisfy this evidence-promotion gate.

## Failure behavior

- Invalid schema, hash mismatch, incomplete decision, bad timestamp, unknown candidate, missing structure, path escape, or artifact collision fails closed with a typed error.
- Queue generation records empty candidate lists and diagnostics instead of fabricating matches.
- Provider calls remain zero.
- If fewer than 30 cases can be fully verified after human review, P1 reports `BLOCKED` and preserves all decisions.

## Verification

- RED/GREEN unit tests for selection, hashes, pending templates, negative decisions, structural verification, preview approval, immutability, and exact case sets.
- Provider-free CLI tests with temporary SQLite fakes.
- Focused adjudication suite, broader evaluation suite, Ruff, compilation, CRG change review, independent review, full suite once on stable source.
- After the tooling commit, generate the real queue from a clean commit using the pinned local dataset/content store/FTS paths; preserve the immutable queue artifact and stop before promotion.
