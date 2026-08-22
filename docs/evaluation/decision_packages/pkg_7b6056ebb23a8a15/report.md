# VIETLEX PRODUCTION-LIGHT DECISION PACKAGE

## Executive Verdict

**PRODUCTION READINESS: `NOT_PRODUCTION_READY`**  
**Package ID**: `pkg_7b6056ebb23a8a15`  
**Schema Version**: `task3-production-light-v1`  

## Evidence Provenance

| Attribute | Value |
| :--- | :--- |
| Builder Git SHA | `1a922af6774b3500ca59e74621bc60106dcbb98d` |
| Builder Source State SHA-256 | `5ff3dd28ac866b8812e8d799c50915ea08c1ed54bb7f6fc09876bc63fcfd03c8` |
| Builder Git Dirty | `False` |
| Dataset Path | `D:\Download\ProfessionalLegalRAG\app\data\namsyntax_legal_qa_420_curated_v1.json` |
| Dataset SHA-256 | `d6e125030e8dda700667ba00f25162fac76472a9bfa2d087f54e2b5bc73a1fee` |
| Sidecar Path | `D:\Download\ProfessionalLegalRAG\docs\evaluation\adjudication\promotions\gold-adjudication-promotion-curated-v4_20260809_151015_227377\labels_v2.json` |
| Sidecar SHA-256 | `6044c084fd0cfd7b696b7e927ae2df26130e090aa64cf1a3b39a0784c1d8a9bf` |
| Selected Case Count | `40` |
| Selected Case IDs SHA-256 | `02b147618710247b69406c62c37ee1733412cf99c803a3b818cfc0040e78cfd6` |
| Production Benchmark Directory | `none` |
| Benchmark Manifest SHA-256 | `none` |
| Benchmark Results SHA-256 | `none` |
| Online Snapshot Path | `none` |
| Online Snapshot SHA-256 | `none` |

## 1. Offline Golden Quality

### Dataset Coverage

- Total cases: `420`
- Answerable cases: `245`
- Unanswerable cases: `175`

### Evidence Verification Coverage

- Total evidence items: `484`
- Verified evidence items: `53`
- Verified evidence coverage: `0.1095`
- All-required-verified cases: `40`
- All-required-verified coverage: `0.0952`
- Unresolved required evidence: `256`

### Production Retrieval Benchmark

- Benchmark Status: `NOT_RUN`
- Readiness Eligible: `False`

## 2. Online No-Gold Proxy

- Status: `NOT_AVAILABLE`
- Designation: `NON_GOLD_NON_GATING_PROXY`
- Record Count: `0`
- Ragas Selected / Executed: `0 / 0`
- Faithfulness (mean): `None` (observed `0` / missing `0`)
- Answer Relevance (mean): `None` (observed `0` / missing `0`)
- Ragas Error Count: `0`

## 3. Operational Reliability

- Status: `NOT_AVAILABLE`
- Total Requests: `0`
- Technical Error Count / Rate: `0` / `None`
- No-Evidence Count / Rate: `0` / `None`
- Context Present Count / Rate: `0` / `None`
- Latency Mean / p50 / p95: `None` / `None` / `None` s
- Telemetry Completeness Rate: `None`

## 4. Human Feedback

### Human Adjudication

- Total Evidence Count: `484`
- Verified Evidence Count: `53`
- Required Unresolved Count: `256`
- All-Required-Verified Cases: `40`

### User Feedback

- Status: `NOT_AVAILABLE`
- Feedback Observed Count: `0`
- Positive / Negative Counts: `0` / `0`
- Positive Rate: `None`

## 5. Production Readiness Gates

| Gate | Status | Notes / Blockers |
| :--- | :---: | :--- |
| `human_feedback_gate` | `NON_GATING` | Human sentiment does not prove retrieval correctness. |
| `online_ragas_proxy_gate` | `NON_GATING` | Ragas is a non-gold, non-gating proxy. |
| `operational_reliability_gate` | `NON_GATING` | Operational success does not prove answer correctness. |
| `production_benchmark_quality_gate` | `NOT_RUN` | {'threshold_evaluations': {}, 'ineligibility_reasons': ['missing_production_retrieval_benchmark']} |
| `verified_gold_coverage_gate` | `INSUFFICIENT_EVIDENCE` | Current verified slice covers 40/420 (9.52%) cases and 53/484 (10.95%) evidence items. Whole-production cutover requires approved verified coverage governance. |

## 6. Blockers / Missing Evidence

1. `insufficient_verified_gold_coverage_governance`
2. `missing_production_retrieval_benchmark`

## Interpretation Boundaries

- Operational success does not prove answer correctness.
- Ragas is a non-gold, non-gating proxy.
- Human sentiment does not prove retrieval correctness.
- P3 partial evidence is excluded from production readiness.
- Missing evidence is not represented as zero.
- No composite quality score is produced.

