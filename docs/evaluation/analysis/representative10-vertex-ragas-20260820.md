# Representative-10 Vertex/Ragas diagnosis — 2026-08-20

## Decision

`NOT PRODUCTION-READY`. Do not run or promote a full golden benchmark from this
result. The ten-case subset failed the repository retrieval gate before the
reranker and answer model could be evaluated on verified evidence.

## Evaluated slice

- Cases: `case_017`, `case_036`, `case_061`, `case_101`, `case_165`,
  `case_243`, `case_261`, `case_323`, `case_329`, `case_397`.
- Verified required evidence: 14 items from two documents (`72/2020/QH14` and
  `59/2020/QH14`).
- Runtime: rewrite off, guardrails shadow, current reranker, concurrency 1.
- Generation, guardrail LLM, and scored Ragas judge: Google Vertex AI
  `gemini-3.5-flash` through ADC.

## Measured results

- Status: 10/10 completed; no recorded judge/provider fallback.
- Retrieval: Document Recall@1/3/5/10/24 = `0`; document/article/clause MRR =
  `0`; nDCG@10 = `0`; exact-reference hit = `0`; multi-hop full/partial = `0`.
- Stage survival: Pinecone candidates `0`; FTS candidates `120`; source gold
  `0/14`; reranker-input gold `0/14`; reranker-output gold `0/14`; final gold
  `0/14`. All 14 first losses are `source_retrieval_metrics`.
- Answers: token F1 `0.1281`; character F1 `0.1898`; ROUGE-L `0.1074`; CHRF
  `0.1776`; answer similarity pass rate `0`.
- Ragas coverage: 5/10 because the evaluator intentionally skipped five
  `pure_refusal` answers. On the five scored answers: faithfulness `0.60`,
  answer accuracy `0.10`, context precision `0.20`, context recall `0.30`.
  All five scored calls used `Google Vertex AI/gemini-3.5-flash`.
- Guardrail shadow results: input safe 3/10 and output safe 9/10. Because all
  inputs are verified legal questions, input blocking is an apparent 7/10
  false-positive rate. The input prompt was subsequently calibrated to allow
  lawful questions about public authorities/policy and to allow ambiguous
  inputs. Follow-up calibration results are recorded below.
- Latency: input guardrail p50 `0.976s`; output guardrail p50 `1.033s`;
  retrieval p50 `2.260s`; end-to-end p50 `8.650s` and p95 `11.955s`.

## Root-cause probe and artifact caveat

A bounded live probe after the run reproduced `HTTP 404 page not found` at
Qdrant query embedding for `case_017`. The Pinecone index itself is ready,
384-dimensional, dot-product, and contains 518,255 records in
`legal-documents-v1`. Therefore the dense lane never reached Pinecone in this
run; FTS alone produced the 12 candidates per case.

The immutable run report says retrieval technical-error rate `0%` because the
pre-fix runner labeled successful lexical fallback as `ok`. Source now reports
this state as `partial_retrieval_error`: quality remains scoreable while the
retrieval technical-error numerator increments. The original immutable report
is retained rather than rewritten.

This run does **not** establish that 384 dimensions are insufficient. A valid
dimension/model A/B requires identical corpus, query set, prefixes, and
retrieval topology. The isolated Vertex embedding latencies around 512–918 ms
are provider/API elapsed times; repeat cosine `1.0` means deterministic repeated
vectors, not one millisecond and not a cosine error.

## Golden-data limitation

The promoted sidecar contains only 40/420 fully eligible verified cases and
53/484 verified evidence items, concentrated in two documents. A production
verified run of 50 cases is not currently possible. Ten additional unverified
cases may be diagnostic only and must not be mixed into production retrieval
denominators.

## Next valid gate

Restore or replace the configured Qdrant inference endpoint/collection, confirm
a one-case dense query returns Pinecone candidates, then rerun the same ten
case IDs. Only proceed to the 40 verified cases when document Recall@24 and
technical-error gates pass. Do not call a 40+10 mixed run a verified 50-case
production benchmark.

## Follow-up validation

- A read-only endpoint probe returned the same plain-text `HTTP 404 page not
  found` for `/`, `/collections`, `/healthz`, and `/readyz`; the Qdrant SDK
  `get_collections()` call also returned 404. This locates the failure before
  collection lookup, model inference, and Pinecone query. No alternate Qdrant
  endpoint was present in the local `D:\Download` configurations.
- The remaining input-rail false positive returned the raw model completion
  `Đánh giá (yes/no): no`. NeMo's fallback parser inspected the first two words,
  encountered `yes` inside the echoed label, and treated the safe `no` decision
  as unsafe. The Vertex guardrail adapter now normalizes a final standalone
  `yes` or `no` before NeMo parses it.
- A post-fix live input-rail rerun over the same ten case IDs produced `10/10`
  safe, `0` blocks, and `0` technical errors. Mean per-case latency was
  `1.816s`; the separate cold warm-up took `13.280s`. This validates input
  calibration only and does not change the failed retrieval production gate.
