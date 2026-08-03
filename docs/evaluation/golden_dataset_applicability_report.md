# GOLDEN DATASET APPLICABILITY REPORT — namsyntax_legal_qa_420

**Dataset**: `app/data/namsyntax_legal_qa_420.json`  
**Total Test Cases**: `420`  
**Sidecar Labels**: `docs\evaluation\gold_labels\namsyntax_legal_qa_420_labels.json`  

## 1. Dataset Breakdown by Question Type

| Question Type | Count | Percentage |
| :--- | ---: | ---: |
| `factoid` | 142 | 33.8% |
| `unanswerable` | 175 | 41.7% |
| `multi-hop` | 103 | 24.5% |

## 2. Deterministic Verification & Label Coverage

| Label Status | Snippet Count | Description |
| :--- | ---: | :--- |
| `document_not_found` | 268 | Cases/snippets with status document_not_found |
| `unanswerable` | 175 | Cases/snippets with status unanswerable |
| `ambiguous` | 27 | Cases/snippets with status ambiguous |
| `verified` | 12 | Cases/snippets with status verified |

## 3. Detailed Verification Metrics

- **Verified Document Labels**: `12`
- **Verified Article Labels**: `10`
- **Verified Clause Labels**: `9`
- **Multi-Hop All-Evidence Verified**: `0 / 103`
- **Duplicate Question Text**: `0`

## 4. Skip Reasons & Corpus Mismatch Notes

- `unanswerable`: Unanswerable test cases explicitly have no assigned gold document.
- `document_not_found`: Snippets whose full legal document was not indexed in the current local content store sample.
- `ambiguous`: Snippets matching multiple legal documents.
