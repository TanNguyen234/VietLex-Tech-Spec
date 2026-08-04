# GOLDEN DATASET APPLICABILITY REPORT V2 — namsyntax_legal_qa_420

**Dataset**: `app/data/namsyntax_legal_qa_420.json`  
**Total Test Cases**: `420`  
**Total Evidence Items**: `482`  
**Sidecar Labels V2**: `docs\evaluation\gold_labels\namsyntax_legal_qa_420_labels_v2.json`  
**Schema Version**: `2.0.0`  

## 1. Dataset Breakdown by Question Type

| Question Type | Case Count | Percentage |
| :--- | ---: | ---: |
| `factoid` | 142 | 33.8% |
| `unanswerable` | 175 | 41.7% |
| `multi-hop` | 103 | 24.5% |

## 2. Deterministic Verification Counts (by Evidence Item)

| Evidence Status | Item Count | % of Evidence Items | Description |
| :--- | ---: | ---: | :--- |
| `no_citation_extracted` | 228 | 47.3% | Items with status no_citation_extracted |
| `unanswerable` | 175 | 36.3% | Items with status unanswerable |
| `not_found_by_local_deterministic_audit` | 78 | 16.2% | Items with status not_found_by_local_deterministic_audit |
| `document_found_anchor_not_found` | 1 | 0.2% | Items with status document_found_anchor_not_found |

## 3. Case-Level Verification Summary

| Case Verification Category | Case Count | % of Test Cases |
| :--- | ---: | ---: |
| `no_citation_extracted` | 187 | 44.5% |
| `unanswerable` | 175 | 41.7% |
| `not_found_by_local_deterministic_audit` | 57 | 13.6% |
| `document_found_anchor_not_found` | 1 | 0.2% |

## 4. Verification Confidence Breakdown

| Confidence Identifier | Item Count | Description |
| :--- | ---: | :--- |
| `unverified` | 482 | Verification confidence level unverified |

## 5. Detailed Metric Counters

- **Verified Document Labels**: `0`
- **Verified Article Labels**: `0`
- **Verified Clause Labels**: `0`
- **Multi-Hop All-Evidence Verified**: `0 / 103`
- **Duplicate Question Text**: `0`
