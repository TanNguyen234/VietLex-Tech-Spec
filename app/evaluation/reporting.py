from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
from app.evaluation.schemas import EvaluationRunManifest


def generate_markdown_report(
    manifest: EvaluationRunManifest,
    retrieval_summary: Dict[str, Any],
    stage_survival_summary: Dict[str, Any],
    latency_summary: Dict[str, Dict[str, float]],
    answer_summary: Optional[Dict[str, Any]] = None,
    case_results: List[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = []
    lines.append(f"# VIETLEX EVALUATION REPORT — {manifest.run_id}")
    lines.append("")
    lines.append(f"**Run ID**: `{manifest.run_id}`  ")
    lines.append(f"**UTC Timestamp**: `{manifest.utc_timestamp}`  ")
    lines.append(f"**Git Commit SHA**: `{manifest.git_sha}`  ")
    lines.append(f"**Dataset Revision**: `{manifest.dataset_revision}`  ")
    lines.append(f"**Dataset SHA-256**: `{manifest.dataset_sha256}`  ")
    lines.append(f"**Configuration Fingerprint**: `{manifest.configuration_fingerprint}`  ")
    lines.append(f"**Execution Command**: `{manifest.command}`  ")
    lines.append(f"**Evaluation Mode**: `{manifest.eval_mode}` | **Judge**: `{manifest.judge_mode}` | **Guardrails**: `{manifest.guardrail_mode}`  ")
    lines.append(f"**Query Rewrite**: `{manifest.rewrite_mode}` | **Reranker**: `{manifest.reranker_provider}`  ")
    lines.append("")

    lines.append("## 1. Retrieval Performance Summary")
    lines.append("")
    lines.append("| Metric | Value | Numerator / Denominator | Notes |")
    lines.append("| :--- | ---: | :---: | :--- |")

    tot = retrieval_summary.get("total_cases", 0)
    scored = retrieval_summary.get("scored_cases_count", 0)
    cov = retrieval_summary.get("coverage", 0.0)

    lines.append(f"| Scored Coverage | {cov * 100:.1f}% | {scored}/{tot} | Cases with verified gold labels |")
    lines.append(f"| No Candidate Rate | {retrieval_summary.get('no_candidate_rate', 0.0) * 100:.1f}% | {retrieval_summary.get('no_candidate_count', 0)}/{tot} | Empty candidate set |")
    lines.append(f"| Retrieval Error Rate | {retrieval_summary.get('retrieval_error_rate', 0.0) * 100:.1f}% | {retrieval_summary.get('retrieval_error_count', 0)}/{tot} | Hybrid/FTS errors |")
    lines.append(f"| Reranker Error Rate | {retrieval_summary.get('reranker_error_rate', 0.0) * 100:.1f}% | {retrieval_summary.get('reranker_error_count', 0)}/{tot} | Reranker API errors |")

    doc_rec = retrieval_summary.get("doc_recall", {})
    art_rec = retrieval_summary.get("article_recall", {})
    cl_rec = retrieval_summary.get("clause_recall", {})

    def safe_val(d: dict, key: Any, default: float = 0.0) -> float:
        if not isinstance(d, dict):
            return default
        v = d.get(key)
        if v is None:
            v = d.get(str(key))
        if v is None or not isinstance(v, (int, float)):
            return default
        return float(v)

    lines.append(f"| Document Recall @ 1 | {safe_val(doc_rec, 1):.4f} | - | Primary legal document hit |")
    lines.append(f"| Document Recall @ 3 | {safe_val(doc_rec, 3):.4f} | - | Top 3 document candidates |")
    lines.append(f"| Document Recall @ 5 | {safe_val(doc_rec, 5):.4f} | - | Top 5 document candidates |")
    lines.append(f"| Document Recall @ 10 | {safe_val(doc_rec, 10):.4f} | - | Top 10 document candidates |")
    lines.append(f"| Document Recall @ 24 | {safe_val(doc_rec, 24):.4f} | - | Pinecone max top_k limit |")
    lines.append(f"| Article Recall @ 1 | {safe_val(art_rec, 1):.4f} | - | Top 1 article candidate |")
    lines.append(f"| Article Recall @ 3 | {safe_val(art_rec, 3):.4f} | - | Top 3 article candidates |")
    lines.append(f"| Article Recall @ 6 | {safe_val(art_rec, 6):.4f} | - | Top 6 article candidates |")
    lines.append(f"| Clause Recall @ 1 | {safe_val(cl_rec, 1):.4f} | - | Top 1 clause candidate |")
    lines.append(f"| Clause Recall @ 3 | {safe_val(cl_rec, 3):.4f} | - | Top 3 clause candidates |")
    lines.append(f"| Clause Recall @ 6 | {safe_val(cl_rec, 6):.4f} | - | Top 6 clause candidates |")
    lines.append(f"| Article MRR | {safe_val(retrieval_summary, 'mrr_article'):.4f} | - | Mean Reciprocal Rank |")
    lines.append(f"| nDCG @ 10 | {safe_val(retrieval_summary, 'ndcg_10'):.4f} | - | Normalized DCG |")
    lines.append(f"| Exact Citation Hit Rate | {safe_val(retrieval_summary, 'exact_reference_hit_rate') * 100:.1f}% | - | Article level citation hit |")
    lines.append(f"| Multi-Hop All-Coverage | {safe_val(retrieval_summary, 'all_hop_coverage_rate') * 100:.1f}% | - | All required evidence hits |")
    lines.append(f"| Multi-Hop Partial-Coverage | {safe_val(retrieval_summary, 'partial_hop_coverage_rate') * 100:.1f}% | - | At least one required hit |")
    lines.append("")

    if answer_summary:
        lines.append("## 2. Generation & Answer Accuracy Summary")
        lines.append("")
        lines.append("| Metric | Value | Notes |")
        lines.append("| :--- | ---: | :--- |")
        lines.append(f"| Answerable Accuracy | {answer_summary.get('answerable_accuracy', 0.0) * 100:.1f}% | Token F1 >= 0.50 |")
        lines.append(f"| Unanswerable Accuracy | {answer_summary.get('unanswerable_accuracy', 0.0) * 100:.1f}% | Honest refusal classification |")
        lines.append(f"| Refusal Precision | {answer_summary.get('refusal_precision', 0.0) * 100:.1f}% | Correct refusals / Total refusals |")
        lines.append(f"| Refusal Recall | {answer_summary.get('refusal_recall', 0.0) * 100:.1f}% | Correct refusals / Unanswerable cases |")
        lines.append(f"| Token F1 | {answer_summary.get('token_f1', 0.0):.4f} | Unigram token F1 |")
        lines.append(f"| Character F1 | {answer_summary.get('char_f1', 0.0):.4f} | 3-gram character F1 |")
        lines.append(f"| ROUGE-L | {answer_summary.get('rouge_l', 0.0):.4f} | Word LCS F1 |")
        lines.append(f"| CHRF | {answer_summary.get('chrf', 0.0):.4f} | Character n-gram F-score |")
        lines.append(f"| Citation Precision | {answer_summary.get('citation_precision', 0.0):.4f} | Valid citations / Total generated |")
        lines.append(f"| Invalid Citation Rate | {answer_summary.get('invalid_citation_rate', 0.0) * 100:.1f}% | Hallucinated citations |")
        lines.append("")

    lines.append("## 3. Stage-Level Latency Breakdown")
    lines.append("")
    lines.append("| Stage / Operation | P50 (s) | P95 (s) | Mean (s) | Min (s) | Max (s) |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")

    for stage, stats in latency_summary.items():
        lines.append(
            f"| `{stage}` | {stats['p50']:.4f}s | {stats['p95']:.4f}s | "
            f"{stats['mean']:.4f}s | {stats['min']:.4f}s | {stats['max']:.4f}s |"
        )
    lines.append("")

    if stage_survival_summary and "average_candidates_per_stage" in stage_survival_summary:
        lines.append("## 4. Stage-Level Candidate Survival & Retention")
        lines.append("")
        lines.append("| Retrieval Stage | Survival Rate | Avg Candidates per Query |")
        lines.append("| :--- | ---: | ---: |")
        surv = stage_survival_summary.get("stage_survival_rates", {})
        avgs = stage_survival_summary.get("average_candidates_per_stage", {})
        for stage_name, rate in surv.items():
            avg_val = avgs.get(f"avg_{stage_name.replace('_chunks', '').replace('_ids', '')}", 0.0)
            lines.append(f"| `{stage_name}` | {rate * 100:.1f}% | {avg_val:.2f} |")
        lines.append("")

    if case_results:
        lines.append("## 5. Case-by-Case Execution Details")
        lines.append("")
        lines.append("| Case ID | Group | Status | Latency | Article Recall | Token F1 | Refusal Category |")
        lines.append("| :---: | :--- | :--- | ---: | ---: | ---: | :--- |")
        for res in case_results:
            cid = res.get("case_id", "N/A")
            grp = res.get("question_type", "factoid")
            st = res.get("status", "ok")
            lat = res.get("latency", {}).get("t_total", res.get("latency", {}).get("t_retrieval", 0.0))
            m = res.get("metrics", {})
            art_rec_val = m.get("article_recall", {}).get(3, "-") if isinstance(m.get("article_recall"), dict) else "-"
            art_rec_str = f"{art_rec_val:.2f}" if isinstance(art_rec_val, (int, float)) else str(art_rec_val)
            tok_f1_val = m.get("token_f1", "-")
            tok_f1_str = f"{tok_f1_val:.2f}" if isinstance(tok_f1_val, (int, float)) else str(tok_f1_val)
            cat = res.get("refusal_category", "-")
            lines.append(f"| `{cid}` | {grp} | {st} | {lat:.2f}s | {art_rec_str} | {tok_f1_str} | `{cat}` |")
        lines.append("")

    return "\n".join(lines)


def write_run_report(
    run_dir: Path,
    manifest: EvaluationRunManifest,
    retrieval_summary: Dict[str, Any],
    stage_survival_summary: Dict[str, Any],
    latency_summary: Dict[str, Dict[str, float]],
    answer_summary: Optional[Dict[str, Any]] = None,
    case_results: List[Dict[str, Any]] = None,
) -> Path:
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    report_content = generate_markdown_report(
        manifest,
        retrieval_summary,
        stage_survival_summary,
        latency_summary,
        answer_summary,
        case_results,
    )
    report_path = run_dir / "report.md"
    temp_path = report_path.with_suffix(".md.tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        f.write(report_content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, report_path)
    return report_path
