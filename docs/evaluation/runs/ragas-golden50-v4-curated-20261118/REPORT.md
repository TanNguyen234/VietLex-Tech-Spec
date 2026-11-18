# Ragas audit of saved Golden50 answers (`ragas-golden50-v4-curated-20261118`)

- **Source Answer Run:** `answer-golden50-v4-curated-20261118`
- **Metric Version:** `ragas-0.4.3`
- **Observed Judge Models:** `google_vertex_ai/gemini-3.5-flash`

```json
{
  "faithfulness": {
    "mean": 0.6456544566544566,
    "numerator": 32.28272283272283,
    "denominator": 50,
    "total_cases": 50,
    "coverage": 1.0,
    "skipped": 0,
    "skip_reasons": {},
    "technical_errors": []
  },
  "answer_accuracy": {
    "mean": 0.29,
    "numerator": 14.5,
    "denominator": 50,
    "total_cases": 50,
    "coverage": 1.0,
    "skipped": 0,
    "skip_reasons": {},
    "technical_errors": []
  },
  "context_precision": {
    "mean": 0.28911564623409863,
    "numerator": 14.166666665470833,
    "denominator": 49,
    "total_cases": 50,
    "coverage": 0.98,
    "skipped": 1,
    "skip_reasons": {
      "technical_error": 1
    },
    "technical_errors": [
      {
        "case_id": "case_047",
        "error": "InstructorRetryException: Connection error."
      }
    ]
  },
  "context_recall": {
    "mean": 0.3037037037037037,
    "numerator": 13.666666666666666,
    "denominator": 45,
    "total_cases": 50,
    "coverage": 0.9,
    "skipped": 5,
    "skip_reasons": {
      "technical_error": 5
    },
    "technical_errors": [
      {
        "case_id": "case_023",
        "error": "InstructorRetryException: Connection error."
      },
      {
        "case_id": "case_024",
        "error": "InstructorRetryException: Connection error."
      },
      {
        "case_id": "case_027",
        "error": "InstructorRetryException: Connection error."
      },
      {
        "case_id": "case_031",
        "error": "InstructorRetryException: Connection error."
      },
      {
        "case_id": "case_047",
        "error": "InstructorRetryException: Connection error."
      }
    ]
  }
}
```

Secondary LLM-judge evidence only; evaluated over saved unchanged answers and prompt contexts with zero online semaphore retention and zero DB writes. Does not certify independent human legal approval.
