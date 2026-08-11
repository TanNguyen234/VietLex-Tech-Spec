# VietLex Evaluation Current Status

**Status (2026-08-11):** P2 retrieval baseline `COMPLETED`; Qdrant structural v2 code-prepared and locally audited; remote pilot phases `NOT RUN`; production readiness **NOT DEMONSTRATED**.

The P3 structural contract has since been hardened locally for recall-oriented reindexing. Corpus membership remains the independent 827-document primary-law scope, not the two documents referenced by golden labels. Inference text is now `vietlex-structural-document-v2`; the model probe uses 1,748 relevant rows, 825 real corpus negatives, and 64 canaries, with no synthetic rows. Default probe execution no longer calls Pinecone inference. These source changes invalidate the earlier plan/source hashes for remote execution; new provider-free audit/plan artifacts must be generated before any user-run `create` command.

New quality gates are exact: probe gold Document Recall@10 `1.0`, probe structural Recall@10 `>=0.95`, canary Document Recall@10 `>=0.90`; final fused Document Recall@24 `1.0`, applicable Article Recall@24 `>=0.95`, applicable Clause Recall@24 `>=0.90`, all-required coverage `>=0.95`, and zero no-candidate/retrieval/reranker error rates. These are acceptance targets, not measured results. Current measured retrieval remains the P2 zero-recall baseline until the user runs the new remote reindex and benchmark phases.

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

## P2 completed baseline

P2 compared these profiles on the exact same 40 selected cases and source state:

1. `legacy`
2. `separated_no_intent`
3. `separated_intent`

Pinned runtime flags were `rewrite=off`, `reranker=current`, `concurrency=1`, `verified-only=true`, and `gold-policy=all-required-verified`.

- Live source Git SHA: `aa3208c850d8b8f8782bab98ca925228202dfff8`; `git_dirty=false`.
- Live source-state SHA-256: `4c4a9c600ee59271052b746944bf5273ad6e64ae36b2332c45afa624a6b8b91d`.
- Selected-case-set SHA-256: `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6`.
- Preflight: `docs/evaluation/preflight/p2-ready-20260809-aa3208c/`; batch `OK`; provider calls 0; 40 cases; all three profiles shared the exact provenance above.
- Successful run IDs: `p2-legacy-aa3208c`, `p2-separated-no-intent-aa3208c`, `p2-separated-intent-aa3208c`.
- Comparison: `docs/evaluation/comparisons/p2-aa3208c/`.
- Comparison JSON SHA-256: `e6b45624c25095e2110de61f92b92fe2b0b93d1eaca4b6960feaaa4745495a7a`.
- Comparison report SHA-256: `4b4a11e8b1358214a0801351e8aecea669aee41deb3a814f35a5b2cd3300dc17`.
- Comparison was generated from clean Git SHA `944d3c996bddcd395d539e62dab4e8ba4bbb33c6`.

### Deterministic result

All three profiles produced the same failed retrieval quality:

- Status: 40/40 `ok`; scored 40; skipped 0; coverage 40/40.
- Document Recall@1, @3, @5, @10, and @24: `0/53` (`micro=0`, `macro=0`).
- Article Recall@3: `0/30`; 27 scored cases, 13 skipped because no applicable article gold.
- Clause Recall@3: `0/14`; 13 scored cases, 27 skipped because no applicable clause gold.
- Document MRR: `0/40`; nDCG@10 numerator `0`, denominator `48.20209`.
- Exact legal-reference hit: `0/40`.
- Multi-hop all-required coverage: `0/40`; partial coverage: `0/53`.
- No-candidate rate: `0/40`; retrieval technical-error rate: `0/40`; reranker technical-error rate: `0/40`.
- First loss: all 53 verified evidence items were absent at `source_retrieval_metrics`; document IDs `427301` and `431147` appeared in zero Pinecone, FTS, merged, resolved, structural, local-selection, reranker-input/output, or final traces.
- Reranker contribution is not measurable because zero verified gold reached the reranker input.
- Recommendation: none. Changing local intent scoring or larger post-source capacities cannot recover documents absent from both initial retrieval sources.

Total-latency summaries:

| Profile | Mean (s) | P50 (s) | P95 (s) | Max (s) |
| :--- | ---: | ---: | ---: | ---: |
| `legacy` | 5.9857 | 4.1813 | 13.9039 | 18.0353 |
| `separated_no_intent` | 6.9185 | 4.7377 | 14.1178 | 31.5816 |
| `separated_intent` | 6.4889 | 4.1044 | 15.5088 | 19.6317 |

Configured provider identifiers are provenance only. The current `RetrievalCaseResult` does not persist which reranker fallback actually served each request. The production Qdrant inference/rerank clients may use ephemeral staging points; no corpus ingestion, durable Pinecone index/namespace change, Qdrant collection recreation, local store/FTS mutation, generation, Ragas, guardrail evaluation, migration, or deployment was executed.

The verified subset is 40 curated cases from the 420-case evaluation dataset, not 40 cases independently sampled from all 518,255 corpus documents. The 53 promoted evidence items point to two pinned corpus documents, so the result diagnoses retrieval for this verified legal slice, not whole-corpus accuracy.

## Qdrant structural v2 local handoff

The opt-in implementation is complete locally through deterministic benchmark code. Pinecone v1 remains the production backend and `get_legal_retriever()` is unchanged. No Qdrant or Pinecone data was created, uploaded, finalized, verified, benchmarked, deleted, or switched during this work.

Provider-free local evidence:

The earlier `*-task8-verified` and `*-provenance-v2` directories are retained as immutable history but are superseded for remote authorization by the recall-hardening artifacts below.

- Audit directory: `docs/evaluation/index-pilots/structural-recall-hardening-audit-20260811/`.
- Audit manifest SHA-256: `8b991baa8cb889cd4acf37cfcd09bb7304190b66758b9a2e717eee8cdb2686f8`.
- Audit `plan.json` file SHA-256: `af514dfb5253afc146a299815c7bd93f5bbfcf5860d23d4f630e904614396196`.
- Audit internal plan SHA-256: `4637bddf820b2f4ce496e886becee1de879d279f46c2a6f32c4bc31a3706e16d`.
- Audit result: 827 documents, 134,334 structural records, provider calls 0.
- Capacity directory: `docs/evaluation/index-pilots/structural-recall-hardening-plan-blocked-20260811/`.
- Capacity `plan.json` file SHA-256: `ba328ebe50c983314e1479f14de422f10f638d52b7449ebda05b995f9f9eeaea`.
- Internal plan SHA-256: `1c6c9e9b338e8e0c9397218ef1772eec1e220286c30ad51ec97fe2639cd827b7`.
- Bound source-state SHA-256: `18adf38b44083d3b0aa2ae7edd9239cd769fa3f99c5a71ac241e6d8212cae31a`; Git SHA `37e17d0fc9e8b7b6ba9f10ff5095017db0411073`. The capacity artifact honestly records `source_git_dirty=true` because the preceding immutable audit directory was untracked; the content-canonical source hash remained identical.
- Source-state semantics are content-canonical: the same repository-visible source paths and bytes now retain the same hash across untracked, staged, and committed states. Git SHA, dirty flags, and diff SHA remain separate provenance.
- Capacity inputs: 4 GiB disk, 1 GiB RAM, 0.5 vCPU, one shard; `existing_disk_bytes` deliberately absent.
- Conservative projected storage: 1,304,087,609 bytes. Capacity result: `BLOCKED_CAPACITY`, with the sole missing input `existing_disk_bytes`; provider calls 0. This plan cannot authorize `create`.

Remote phase status: `create NOT RUN`; `probe-model NOT RUN`; `upload NOT RUN`; `finalize NOT RUN`; `verify NOT RUN`; `benchmark NOT RUN`. Generation, Ragas, and guardrails are disabled by the benchmark contract.

After obtaining current Qdrant disk usage, regenerate a clean `PASS_CAPACITY` plan. The exact binding values currently demonstrated by the local blocked plan are:

```powershell
$PLAN = "docs/evaluation/index-pilots/structural-recall-hardening-plan-blocked-20260811/plan.json"
$PLAN_SHA = "1c6c9e9b338e8e0c9397218ef1772eec1e220286c30ad51ec97fe2639cd827b7"
$SOURCE_SHA = "18adf38b44083d3b0aa2ae7edd9239cd769fa3f99c5a71ac241e6d8212cae31a"
$COLLECTION = "vietlex-legal-rag-v2-pilot"
$DATASET = "app/data/namsyntax_legal_qa_420_curated_v1.json"
$SIDECAR = "docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json"
$P2 = "docs/evaluation/comparisons/p2-aa3208c/comparison.json"
$P2_SHA = "e6b45624c25095e2110de61f92b92fe2b0b93d1eaca4b6960feaaa4745495a7a"
```

Do not run `create` with the blocked plan above. Once a regenerated plan records `PASS_CAPACITY`, replace `$PLAN`, `$PLAN_SHA`, and `$SOURCE_SHA` with that artifact's exact values, then run the phase commands in order. Each downstream `<..._SHA256>` must be the real SHA-256 of the immediately preceding immutable artifact; placeholders are intentionally not fabricated.

```powershell
python run_structural_index_pilot.py create --plan $PLAN --plan-sha256 $PLAN_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --allow-remote-write
python run_structural_index_pilot.py probe-model --plan $PLAN --create-receipt <CREATE_RECEIPT> --create-receipt-sha256 <CREATE_SHA256> --dataset $DATASET --sidecar $SIDECAR --plan-sha256 $PLAN_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --allow-remote-write
python run_structural_index_pilot.py upload --plan $PLAN --create-receipt <CREATE_RECEIPT> --create-receipt-sha256 <CREATE_SHA256> --probe-report <PROBE_REPORT> --probe-report-sha256 <PROBE_SHA256> --checkpoint <CHECKPOINT> --plan-sha256 $PLAN_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --allow-remote-write
python run_structural_index_pilot.py finalize --plan $PLAN --create-receipt <CREATE_RECEIPT> --create-receipt-sha256 <CREATE_SHA256> --probe-report <PROBE_REPORT> --probe-report-sha256 <PROBE_SHA256> --upload-report <UPLOAD_REPORT> --upload-report-sha256 <UPLOAD_SHA256> --plan-sha256 $PLAN_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --allow-remote-write
python run_structural_index_pilot.py verify --plan $PLAN --create-receipt <CREATE_RECEIPT> --create-receipt-sha256 <CREATE_SHA256> --probe-report <PROBE_REPORT> --probe-report-sha256 <PROBE_SHA256> --upload-report <UPLOAD_REPORT> --upload-report-sha256 <UPLOAD_SHA256> --finalize-receipt <FINALIZE_RECEIPT> --finalize-receipt-sha256 <FINALIZE_SHA256> --plan-sha256 $PLAN_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --allow-remote-write
python run_structural_retrieval_eval.py benchmark --dataset $DATASET --sidecar $SIDECAR --plan $PLAN --plan-sha256 $PLAN_SHA --create-receipt <CREATE_RECEIPT> --create-receipt-sha256 <CREATE_SHA256> --probe-report <PROBE_REPORT> --probe-report-sha256 <PROBE_SHA256> --upload-report <UPLOAD_REPORT> --upload-report-sha256 <UPLOAD_SHA256> --finalize-receipt <FINALIZE_RECEIPT> --finalize-receipt-sha256 <FINALIZE_SHA256> --verify-receipt <VERIFY_RECEIPT> --verify-receipt-sha256 <VERIFY_SHA256> --p2-baseline $P2 --p2-baseline-sha256 $P2_SHA --source-state-sha256 $SOURCE_SHA --collection $COLLECTION --run-id <UNIQUE_RUN_ID> --allow-remote-benchmark
```

## Execution and verification evidence

- Recall-hardening TDD: Task 1 core RED `17 failed, 16 passed`, then GREEN; Task 2 relevant-only RED `2 failed`, then the real local scope resolved 40 cases, 1,748 relevant rows, 825 hard negatives, and 64 canaries with no skips; Task 3 missing Qdrant-only interface RED then GREEN; Task 4 weak acceptance/reranker-report RED `3 failed`, then GREEN.
- Final recall-hardening affected matrix: `186 passed in 17.80s`.
- Final full suite at clean Git SHA `37e17d0fc9e8b7b6ba9f10ff5095017db0411073`: `569 passed, 1 skipped in 99.05s`; the skip remains the opt-in live integration test.
- Targeted Ruff, compileall, both CLI help commands, and `git diff --check`: exit 0. CRG source graph matched HEAD, risk `0.55` (medium), no affected production flow detected; `app/services/retrieval.py`, `get_legal_retriever()`, and API routes were unchanged.
- New audit and blocked-capacity plan read only the pinned local store and each recorded `provider_calls=0`. No Qdrant/Pinecone client, embedding, reranker, generation, Ragas, or guardrail call was executed.
- Provenance-v2 regression: RED reproduced the untracked/staged hash mismatch; GREEN passed, affected suite `83 passed`, and final full suite `556 passed, 1 skipped`.
- Source-state checkpoint before artifacts and after both immutable artifacts: identical `71e4d8d5a711954c7828924ce6605f7bb8335a3d2289053de770288a5409e8b7`.
- Task 8 affected structural/evaluation suite: `172 passed in 21.07s` before the final Windows-console portability regression; that regression was reproduced RED and passed GREEN independently.
- Task 8 final full suite on stable source: `555 passed, 1 skipped in 103.52s`; the skip is the existing opt-in live integration test.
- Task 8 fatal Ruff checks over all changed code/tests, compileall, both CLI help commands, and `git diff --check`: passed. Repository-wide fatal Ruff found 38 pre-existing F401 findings in `scripts/test_cloudrun_rag_integration.py` and `tests/test_evaluation_framework.py`; no Task 8 file failed.
- Task 8 provider-free audit and blocked-capacity commands read the local content store only. Qdrant/Pinecone clients, generation, Ragas, and guardrails were not constructed; `provider_calls=0` in both artifacts.
- Promotion artifact reload and hash validation: passed.
- Relevant post-promotion suite: `195 passed in 23.70s`.
- Full post-promotion suite: `375 passed, 1 skipped in 59.93s`.
- Runner audit-summary TDD: RED reproduced two intended failures plus the missing-path failure; GREEN `19 passed in 5.78s`.
- Runtime adapter failure was reproduced from the first attempted live run: `AttributeError: 'EvidenceChunk' object has no attribute 'score'`. TDD regression passed after removing the invalid field read; relevant suite `199 passed in 20.11s`.
- Failed immutable run: `docs/evaluation/runs/p2-legacy-d9f76f1/failure.json`; completed cases 0; manifest/results/report were not written.
- Comparison TDD: 3 focused tests passed; comparison plus metrics/reporting/provenance suite: `27 passed in 8.17s`.
- Final focused regression/comparison gate: `4 passed in 5.16s`.
- Final relevant evaluation gate: `202 passed in 20.49s`.
- Final full suite: `382 passed, 1 skipped in 46.85s`; the skip is the existing opt-in live integration test.
- Fatal Ruff checks over `app`, both changed entrypoints, and affected evaluation tests: passed. Compileall and working/staged `git diff --check`: passed.
- A broader Ruff invocation over all legacy tests was also attempted and failed on pre-existing unused imports outside the P2 change scope; those unrelated tests were not mechanically rewritten.
- Real promoted-sidecar selection validation: 420 total cases, 40 selected, 484 evidence items, no implicit audit summary.
- Live retrieval execution: 120 successful case executions plus one aborted first-case attempt; exact provider call count was not instrumented.
- Remote durable corpus/index data modified: no. Ephemeral Qdrant inference/rerank staging may have been created and cleaned by the configured clients.

Execution plan: `docs/superpowers/plans/2026-08-09-vietlex-p2-retrieval-baseline.md`.
