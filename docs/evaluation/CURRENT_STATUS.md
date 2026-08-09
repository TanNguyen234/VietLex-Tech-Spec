# VietLex Evaluation Current Status

**Status (2026-08-09):** P1 promotion `READY_FOR_P2`; P2 clean three-profile retrieval baseline in progress.

- Production readiness: **NOT DEMONSTRATED**.
- Historical 2026-08-03 retrieval runs remain invalid for decisions.
- Deterministic evaluation is primary; Ragas remains opt-in and is disabled for P2.
- No ingestion, corpus/index mutation, generation, or guardrail evaluation is part of P2.

## Promoted verified-gold checkpoint

The user approved exact preview SHA-256 `89138b35c77998c03d797d92c6e9d9a31070abc02bf4becb1a0fb26dbea5387c`. Promotion completed without overwriting the source sidecar.

- Dataset: `app/data/namsyntax_legal_qa_420_curated_v1.json`.
- Dataset SHA-256: `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee`.
- Source sidecar: `docs/evaluation/gold_labels/namsyntax_legal_qa_420_labels_v4.json`.
- Source-sidecar file SHA-256: `7629cec30a5afcd31d1517d142341a053ebe665691093c2742288f0a61433d5c`.
- Promoted sidecar: `docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json`.
- Promoted-sidecar file SHA-256: `6044c084fd0cfd7b696b7e927ae2df26130e090aa64cf1a3b39a0784c1d8a9bf`.
- Promoted canonical sidecar payload SHA-256: `a04cc60c535ded71ea33f3b9b3b6105342b205f5e9f52e6636424ce8388a5089`.
- Promotion summary SHA-256: `25288a79c29f6b4b6534453f3239a49ad742a1f72c4351c4bb961bf837ba55db`.
- Queue SHA-256: `aac86e7921c319da7a82262a04df7df60745e7778aae262940c81791de606435`.
- Decisions SHA-256: `35959b6a89852b717458be5c3694e8899768df7b8f50731535c023fb25741b0b`.
- Counts after reload: 420 cases, 484 evidence items, 53 verified evidence items, 40 cases satisfying `all-required-verified`.
- Selected-case-set SHA-256: `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6`.
- Persisted reviewer identity: `conversation-user`; raw adjudication notes: absent.
- Provider calls during curation/adjudication/promotion: 0.
- Remote data, local corpus, Pinecone, Qdrant, content store, and FTS modified: no.

The earlier curated-v1 queue is retained immutably and explicitly marked superseded. It is not eligible for promotion or P2.

## P2 execution contract

P2 compares these profiles on the exact same 40 selected cases and source state:

1. `legacy`
2. `separated_no_intent`
3. `separated_intent`

Pinned runtime flags are `rewrite=off`, `reranker=current`, `concurrency=1`, `verified-only=true`, and `gold-policy=all-required-verified`. All live manifests must agree on Git SHA, source-state SHA-256, dataset and sidecar SHA-256, selected-case-set SHA-256, dataset revision, metric version, and configured provider identifiers.

Required comparison outputs are document recall by K and stage, Article/Clause recall, MRR, nDCG@10, exact-reference hit, multi-hop coverage, first-loss counts, reranker contribution, no-candidate and technical-error rates, latency, numerators/denominators, coverage, skips, and skip reasons.

Configured provider identifiers are provenance; they do not prove which fallback answered unless runtime diagnostics record it. The verified subset is 40 curated cases from the 420-case evaluation dataset, not 40 samples drawn independently from all 518,255 corpus documents.

## Verification evidence available before P2 live calls

- Promotion artifact reload and hash validation: passed.
- Relevant post-promotion suite: `195 passed in 23.70s`.
- Full post-promotion suite: `375 passed, 1 skipped in 59.93s`.
- Runner audit-summary TDD: RED reproduced two intended failures plus the missing-path failure; GREEN `19 passed in 5.78s`.
- Fatal Ruff checks, compileall, and `git diff --check`: passed; diff check emitted line-ending conversion warnings only.
- Real promoted-sidecar selection validation: 420 total cases, 40 selected, 484 evidence items, no implicit audit summary.
- Live retrieval provider calls: **NOT RUN yet**.
- P2 immutable preflight and live run artifacts: **NOT RUN yet**.

Execution plan: `docs/superpowers/plans/2026-08-09-vietlex-p2-retrieval-baseline.md`.

