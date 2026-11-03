> Update 2026-11-03: Ragas completed on all 50 saved answers (faithfulness 0.8333; accuracy 0.9000; context precision 0.8708; recall 0.9490; zero technical errors). L04 has an AI source review, not independent human legal approval. General production readiness remains unproven. See [release verification](../../tasks/production-readiness-20261103/REPORT.md).

# VietLex v3 Golden-50 evaluation bundle

Latest measurement (2026-11-03): `answer-golden50-production-timeout20-20261103-f93a41fe`, live metric3.2.0, real production-service providers, mandatory guards, judge none; paired offline metric3.3.0 rescore `answer-golden50-offline-metrics33-20261103-2349369e` on exactly the same50answers andcontexts with zero provider/database calls. Exact prompt-context/hash and noncitation metric parity50/50. See [current report](../runs/crg-golden50-20261103-3ee9f610/REPORT.md) for numerators, skips and limits. The September commands/results below remain historical; the current full command uses `--backend production --judge none` and is recorded verbatim in the report receipts.

Updated: 2026-09-03.

This directory is the readable, self-contained input used for the current v3
bounded evaluation. It is not a 50-case sample of all 518,255 documents. Its
verified evidence is present in the audited 14,962-document online Qdrant v3
slice; the dataset selection itself predates and does not represent that expansion.

| File | Contents |
| --- | --- |
| `cases.json` | Exactly 50 questions, sequential evaluator `case_id`, original `source_case_id`, and expected answers |
| `labels.json` | Gold retrieval labels for the same 50 IDs |
| `manifest.json` | Selection, provenance hashes, and denominator audit |

The denominator contract is intentionally split:

- answer, generation, latency, NeMo input/output, and optional Ragas metrics: up to 50 cases, subject to explicitly reported execution failures;
- verified retrieval metrics: 40 labelled cases containing 53 verified evidence items;
- retrieval skips: 10 cases with reason `no_verified_gold_label`;
- Ragas is an opt-in LLM judge, not a deterministic metric or proof of legal correctness.

The selected source case-ID SHA-256 is `56ae294f9698569ab4f7ae11ed87aabfa7c79b616919378dc0f5d4e32e53bdf3`. Runtime IDs are remapped deterministically to `case_001` through `case_050` because the canonical evaluator identifies dataset rows by position; every case and label retains `source_case_id` for traceability.

Run v3 retrieval and answer evaluation explicitly:

```powershell
$env:SERVERLESS_ONLINE_ONLY = "true"
$env:USE_LEGACY_FREE_PIPELINE = "false"

python run_retrieval_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking rrf-dbsf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --run-id YOUR_UNIQUE_RETRIEVAL_RUN_ID

python run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking rrf-dbsf --retrieval-run docs/evaluation/runs/YOUR_UNIQUE_RETRIEVAL_RUN_ID --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --run-id YOUR_UNIQUE_ANSWER_RUN_ID
```

Use a unique run ID; evaluators reserve immutable
`docs/evaluation/runs/<run-id>/` directories and must not overwrite an earlier
run. These commands make paid/live provider calls. Default tests and default
evaluation make zero Ragas calls.

The historical September2026 run pair is:

- `retrieval-v3-golden50-expanded14962-rrf-dbsf-20260903`
- `answer-v3-golden50-expanded14962-rrf-dbsf-20260903`

Retrieval passed its configured gate with zero technical errors: Document
Recall@3 `53/53`, Article Recall@3 `29/30`, and Clause Recall@3 `13/14`. The
answer run completed 50/50 generation, guardrail, and Ragas calls, but
deterministic exact match was `0.0000`, token F1 was `0.2305`, and observed
Ragas faithfulness was `0.8221`. Ragas used Google Vertex AI
`gemini-3.5-flash`, the same model identity observed for generation, so those
judge means are secondary evidence rather than independent legal review. Both
manifests honestly record the dirty source state and its exact diff SHA-256.
