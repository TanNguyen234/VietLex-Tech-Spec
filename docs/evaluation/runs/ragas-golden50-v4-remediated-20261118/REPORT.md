# Ragas audit of saved Golden50 answers (`ragas-golden50-v4-remediated-20261118`)

- **Source Answer Run:** `answer-golden50-v4-remediated-20261118`
- **Metric Version:** `ragas-0.4.3`
- **Observed Judge Models:** `gemini/gemini-2.5-flash, google_vertex_ai/gemini-3.5-flash, groq/openai/gpt-oss-20b`

```json
{
  "faithfulness": {
    "mean": 0.7115378189062399,
    "numerator": 35.576890945311995,
    "denominator": 50,
    "total_cases": 50,
    "coverage": 1.0,
    "skipped": 0,
    "skip_reasons": {},
    "technical_errors": []
  },
  "answer_accuracy": {
    "mean": 0.89,
    "numerator": 44.5,
    "denominator": 50,
    "total_cases": 50,
    "coverage": 1.0,
    "skipped": 0,
    "skip_reasons": {},
    "technical_errors": []
  },
  "context_precision": {
    "mean": 0.8486394557104591,
    "numerator": 41.5833333298125,
    "denominator": 49,
    "total_cases": 50,
    "coverage": 0.98,
    "skipped": 1,
    "skip_reasons": {
      "technical_error": 1
    },
    "technical_errors": [
      {
        "case_id": "case_015",
        "error": "InstructorRetryException: Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jvmbczpre01vs0amtmy3r1qr` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 4473, Requested 4386. Please t"
      }
    ]
  },
  "context_recall": {
    "mean": 0.9333333333333332,
    "numerator": 46.666666666666664,
    "denominator": 50,
    "total_cases": 50,
    "coverage": 1.0,
    "skipped": 0,
    "skip_reasons": {},
    "technical_errors": []
  }
}
```

Secondary LLM-judge evidence only; evaluated over saved unchanged answers and prompt contexts with zero online semaphore retention and zero DB writes. Does not certify independent human legal approval.
