# VietLex — CRG repaired, Golden50 measured, release27 accepted

Run `@RUN@`, 2026-11-03. Golden50 was executed against actual pinned providers, and every final deterministic metric was replayed from the exact saved prompt contexts. This is bounded engineering/retrieval evidence; legal correctness and full-corpus production readiness are not demonstrated.

## Scope and authority

Continued user-authorized repair, real-provider evaluation, ordinary QA authentication and deployment. Current dirty checkout retained; no commit/push/PR, installation, actual .env/credential/quota changes, corpus/index/vector migration/deletion, gold-label rewriting or human legal-evidence promotion. Active-turn model switching unavailable; no Sol claim. CRG and ECC skills applied; optional ECC vendor reference missing, not installed.

## Confirmed fixes and review

- Project CRG command now calls installed2.3.7 directly instead of failing uvx offline-cache resolution. Cached-only HF mode and300s startup bound accommodate measured local prewarm. Actual stdio MCP minimal/build/changes/flows/review/callers/tests results were retrieved. The native mcp__crg namespace later became available and actual native minimal/build/detect/flows/qualified callers/tests succeeded; raw crg-native33 receipts retained. Earlier repair was proven through ClientSession before native exposure.
- Stale graph rebuilt; tracked Git coverage supplemented by installed CodeParser/GraphStore for untracked Python source, then verified through actual MCP. pack_sources26 tests/16 callers; online evaluation stage31 tests. JS grammar unavailable: source/Node fallback. Changed-function graph review capped500 across old dirty work; not an exhaustive review of that preexisting work. Important graph findings source-validated. See raw/investigation/review-receipt.md and MCP receipts.
- Shared citation parser recognizes explicit non-year identifiers such as04/VBHN-NHNN and5020/QĐ-UB. Answer metric3.2.0 recognizes literal ordinal clauses under their own whole-article prompt heading; wrong clause/article/document, partial fragment, decimal and cross-reference negatives remain invalid. This measures locator containment, not whether a legal proposition is supported/current.
- AnswerCaseResult now stores exact prompt_contexts separately from metadata-only prompt_evidence, enabling byte/hash and offline metric replay. JSON roundtrip parity checked. No model/rank/retrieval/prompt/auth contract change in this citation fix.

Focused TDD:6 intended RED failures, then92 passed14.53s. Stable source and directed CRG review preceded fresh full27: **@PYTHON@**; **22 Node passed**. Source27/config/test snapshot is unchanged through full27, offline rescore, staging and fresh acceptance. Live50 was captured on source26; the only changed app file is the offline metrics module, proved by hashes and unchanged online-helper ASTs. Earlier source25/26 verification remains separately scoped. Earlier baseline gates146 and prior Node22 are historical. Exact focused commands are in raw/investigation/citation-focused.log and task receipts; full commands in raw/release27/python-exit.json,node-exit.json.

An isolated replay of the original live case014 uses an identical context SHA256 `facfa7e256e9fb4bb1c90637ea567fef1e14148b5b9163251500e43d5318c942`; the unchanged answer's false invalid-citation score1.0 becomes0.0. That isolated regression is separate from the paired full50 metric3.3 rescore below. The baseline3.1, failed3.2 and successful3.2 live runs remain immutable with their own generated answers; only the later3.3 offline comparison intentionally uses the exact same50answers.

## Measured timeout failure and bounded repair

The first citation3.2 run `answer-golden50-production-citations32-20261103-476b6d5e` completed50 with48ok and2input_guardrail_error(timeout), input/output safe48/50,45observed generations; replay50/50. Its configured retrieval gate **FAILED**, multi-hop37/39=.9487. Both cases46/49 exceeded the8second input-check deadline. This failed run remains immutable and is SHA-indexed alongside the baseline and final run. Candidate25 was staged but never promoted.

Minimal runtime repair: shared GUARDRAIL_TIMEOUT_SECONDS default8 to20seconds; both local NeMo and serverless consume it. No retries/fallback or guard disabling added; cancellation/typed503/unknown safety remain.20seconds is latency headroom, not a promise of availability. RED2failures/17pass; focused108pass52.44s. Actual asynchronous1ms override proves cancellation once; simulated10second input/output checks prove an8second tail no longer truncates valid decisions. Metadata-only production environment query returned30entries, hiddenProductionEnvCount0, no timeout override; no values retained/no environment mutation. CRG minimal/build/detect/flows/context rerun; short-name timeout callers/tests ambiguous across4implementations, so direct source validation used for that bounded ambiguity. Details in timeout-review.md. Fresh full27 and final same50/concurrency2 run followed stable review; old25 source proof remains historical.

## Golden50 evidence

Baseline `answer-golden50-production-enforce-20261103-82280547` completed50/50; final **`@FINAL_RUN@`** completed50/50. Pipeline chat_service_v1/backend production, Vertex/Qdrantv3 rrf-dbsf, rewriteoff, currentreranker, concurrency2, input/output enforce, judge none. APP_ENVdevelopment andSERVERLESS_ONLINE_ONLYtrue select the actual serverless source/guard path in local service execution. These are real Vertex/Qdrant/Supabase calls, separately labelled from deployed HTTP acceptance. Preflight1 also completed before baseline50.

Original cases/labels unchanged:50 answer cases;40 verified retrieval cases/53 evidence items;10 retrieval skips `no_verified_gold_label`. The dataset covers a bounded audited online slice; it is not representative of518255documents. All50 are labelled answerable; expected number/date/entity labels and reference-citation coverage are insufficient for broad legal/refusal conclusions. Each evaluator report/raw metrics includes denominators, coverage and skip reasons; no lexical or citation-containment score proves legal correctness/faithfulness.

Final50 exact context SHA sequences and every per-case deterministic metric reproduce **50/50** with zero additional provider/database calls. Full numeric answer/retrieval/latency summaries, guards, observed model events, errors and configured retrieval gate are in `raw/investigation/fixed50-validation.json`; canonical full reports/raw outputs are referenced and SHA-indexed in `benchmark-references.json`. Ragas was disabled; zero optional judge results/calls. Do not claim50 model generations if no-context cases correctly skip generation; observed generation count is explicit in validation.

Canonical benchmark provenance conservatively redacts whole-workingtree diff because historical public artifact paths include `.env.example.patch`. Sensitive-path rules were preserved. Companion command receipts contain literal tracked `git diff --binary HEAD` SHA256 and explicit app/config/test source snapshots with git_dirty=true; this is a different hash contract from canonical redacted whole-workingtree provenance. Final task manifest records its own literal tracked diff and every artifact hash. Exhaustive untracked inventory UNKNOWN due three preexisting inaccessible scratch directories.


## Full metric3.3: paired offline rescore, same50answers

User explicitly requested full metrics. The source-index attribution bug is fixed in the offline metric module only: resolvable source indices use actual prompt-header identity; explicit legal IDs remain untouched, wrong/conflicting/out-of-range references remain invalid; giant numeric indices cannot crash evaluation. RED7fail then102focusedpass; giant-index RED2 then final104pass16.00s. Native CRG11callers/11tests plus direct source/AST validation; production caller is run_stage_b_offline. New untracked test source reviewed directly; graph coverage not invented.

Immutable **`@OFFLINE_RUN@`** recomputes every deterministic metric on the exact live50 responses/contexts from `@FINAL_RUN@`, with zero provider/database calls. Responses, context hashes, retrieval/provider/guard/latency metadata and all non-citation metrics are unchanged. This is a valid paired scoring correction, not better generated answers or a fresh live50 on deployment27. Parent3.2 scores remain immutable. Full metric definitions, numerators/denominators, coverage/skips, stage metrics, MRR/nDCG, refusal and latency are in **[FULL_METRICS.md](FULL_METRICS.md)** and full-metric-summary.json; paired hashes/source27 proof are in the offline run.

Expected number/date/entity labels are absent (0/50 coverage); citation recall/coverage gold covers only1/50; all50cases are answerable, so refusal recall has no applicable denominator. These are N/A where appropriate, not fabricated zeros or passes. Ragas/LLM judges remain opt-in and NOT RUN, not part of these deterministic scores. Literal citation parsing still has nested/cross-reference limitations; residual invalid rate is an audit signal, not independent legal adjudication. EM/token F1 and currentness limitations prevent a production-ready conclusion.

## Deployment and public acceptance

Primary deployment **`@DEPLOYMENT@`**, appSHA `@APP_SHA@`, configSHA `@CONFIG_SHA@`. Candidate deployment manifest/dry upload/stage identity checked before promotion; concurrent-primary guard checked before alias mutation; primary identity/readiness re-read afterward. Matched frontend static hash checked against tested source.

Fresh local NeMo/Vertex integration (APP_ENVtest, direct service functions, not public HTTP) passed input/output with observed timeout20 and required flows; provider events retained in local-guard-timeout20.json. Fresh frozen8 HTTP200, input/output enforce/executed despite client off/false; two negative input controls rejected despite shadow/false; source/replay/export/Mongo exact context/answer roundtrip8/8; ADMIN own-data and USER cross-owner isolation checked; no quota reset/bypass. Original G7PDF200 readable, scan control200 metadata_only. Readonly database/control receipts and bounded deployment error-log query retained. This is finite acceptance, not universal safety proof.

@CONTENT@

## L04 legal source dossier and remaining boundary

Five newly downloaded official PDFs:08/2022,05/2025,136/2025,49/VBHN-BNNMT2026 and98/VBHN-VPQH2026. URLs, original bytes, hashes/page-text and selected rendered pages retained;20 immutable earlier primary dependencies copied with hashes. All20scan pages of66.25/2026 were rendered and actually read: effective15September2026 (not enactment4September), scoped industrial-park/geology/mineral transfers, transitions limited by subject, and an annex explicitly listing proposed amendments. See legal/review6625/READING.md; no blanket transfer of every NN&MT environmental-permit function is inferred. Operative permit/delegation/effect/transitional clauses formerly blocked by scans now have readable official gazette sources. `raw/investigation/L04-REVIEW-DRAFT.md` gives concrete conditional conclusions and clause map: no general exemption solely from absent wastewater/gas; imported-scrap requirement and statutory exceptions; separate authority/delegation; general18May2026 versus AppendixIXB1July2026; outer28February2027 plus early-termination rules; old permit/pending-file transitions. Missing location/licence/receipt-date/exception facts are not invented.

The migrated national VBPL portal opens in a normal isolated browser; earlier DNS/403 receipts apply only to old endpoints/tools. Actual history/diagram DOM responses are preserved. Its visible list omits146/2025 although official original/consolidated sources establish that amendment; therefore metadata cannot certify a complete chain to frozen29October2026. See legal/inventory-history/INTERPRETATION.md for the actual portal observations and coverage conflict. Search absence and a consolidated text are not proof of exhaustive currentness.

Complete legal-currentness/applicability and independent human legal approval remain **DEFERRED/UNKNOWN**. AGENTS.md: “Human-only legal evidence promotion remains human-only unless the current task explicitly establishes a verified automated contract.” No automated approval contract exists here; agent has not signed or promoted L04. This specific boundary survives the completed technical work. No production-ready claim.

## Reproduction and changed files

PowerShell cwd `D:\Download\ProfessionalLegalRAG`; exact recorded argv/exit receipts govern:

```powershell
.venv\Scripts\python.exe .tmp-finish-real-20261030/run_cycle27.py
.venv\Scripts\python.exe .tmp-finish-real-20261030/crg-golden50-af33f34f/benchmark_timeout.py
.venv\Scripts\python.exe -X utf8 .tmp-finish-real-20261030/crg-golden50-af33f34f/verify_timeout.py
.venv\Scripts\python.exe .tmp-finish-real-20261030/package_stage27.py
.venv\Scripts\python.exe .tmp-finish-real-20261030/crg-golden50-af33f34f/release_accept27.py
```

Benchmark wrappers record exact canonical run_answer_eval.py arguments and process-only env overrides in *-command.json. CRG helpers/actual MCP schema/results and legal collection commands are retained in raw/investigation. Release driver records actual promotion/HTTP/roundtrip/guard/database/frontend/log argv and exit status in execution-final25.json. Source27 packaging ran after full27 and offline metric rescore; no source changed and promotion waited for successful final replay.

Source/config changes: .codex/config.toml, .code-review-graphignore, app/evaluation/legal_citations.py, answer_metrics.py, schemas.py, root run_answer_eval.py, app/config.py (bounded default20seconds). Tests: test_evidence_citation_scope.py, test_chat_pipeline_parity.py, test_vietnamese_entity_metrics.py, test_answer_reference_citations.py and tests/services/test_serverless_guardrails.py. Task plan/current status/Golden50 README updated separately. Source copies and stable task delta retained. Prior dirty work was preserved, not represented as entirely reviewed here.

NOT RUN/UNKNOWN: optional Ragas; representative full-corpus/independent legal-quality benchmark; exhaustive legal change inventory and human L04 approval; corpus migration/coverage expansion. These do not erase completed Golden50 or HTTP8/role execution.
