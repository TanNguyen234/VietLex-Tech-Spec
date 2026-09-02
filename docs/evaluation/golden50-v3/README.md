# VietLex v3 Golden-50 evaluation bundle

Updated: 2026-09-01.

This directory is the readable, self-contained input used for the current v3
bounded evaluation. It is not a 50-case sample of all 518,255 documents: its
verified evidence belongs to the audited 4,969-document Qdrant v3 slice.

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

python run_retrieval_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --profile separated_intent --rewrite off --reranker current --concurrency 1 --gold-policy none --run-id YOUR_UNIQUE_RETRIEVAL_RUN_ID

python run_answer_eval.py --dataset docs/evaluation/golden50-v3/cases.json --sidecar docs/evaluation/golden50-v3/labels.json --backend vertex-qdrant-v3 --ranking raw-rrf --retrieval-run docs/evaluation/runs/YOUR_UNIQUE_RETRIEVAL_RUN_ID --profile separated_intent --rewrite off --guardrails enforce --reranker current --concurrency 1 --gold-policy none --judge ragas --run-id YOUR_UNIQUE_ANSWER_RUN_ID
```

Use a unique run ID; evaluators reserve immutable
`docs/evaluation/runs/<run-id>/` directories and must not overwrite an earlier
run. These commands make paid/live provider calls. Default tests and default
evaluation make zero Ragas calls.

The latest comparable run pair is:

- `retrieval-v3-golden50-online-vercel-20260901`
- `answer-v3-golden50-online-vercel-20260901`

Retrieval passed its configured gate with zero technical errors. The answer run
also completed 50/50, but deterministic exact match was `0.0000` and token F1
was `0.2336`. Opt-in Ragas used Google Vertex AI `gemini-3.5-flash`, the same
model identity observed for generation, so those judge means are secondary
evidence rather than independent legal review.
