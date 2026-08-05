from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.evaluation.schemas import EvaluationRunManifest


def fmt_val(v: Any, is_pct: bool = False, decimals: int = 4) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, (int, float)):
        if is_pct:
            return f"{v * 100:.1f}%"
        return f"{v:.{decimals}f}"
    return str(v)


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
    lines.append(f"**Profile**: `{manifest.profile_name}`  ")
    lines.append(f"**UTC Timestamp**: `{manifest.utc_timestamp}`  ")
    lines.append(f"**Git Commit SHA**: `{manifest.git_sha}`  ")
    lines.append(f"**Git Dirty Status**: `{manifest.git_dirty}` (Diff SHA256: `{manifest.git_diff_sha256 or 'clean'}`)  ")
    lines.append(f"**Dataset Revision**: `{manifest.dataset_revision}`  ")
    lines.append(f"**Dataset SHA-256**: `{manifest.dataset_sha256}`  ")
    lines.append(f"**Sidecar SHA-256**: `{manifest.gold_label_sidecar_sha256 or 'N/A'}`  ")
    lines.append(f"**Configuration Fingerprint**: `{manifest.configuration_fingerprint}`  ")
    lines.append(f"**Execution Command**: `{manifest.command}`  ")
    lines.append(f"**Evaluation Mode**: `{manifest.eval_mode}` | **Judge**: `{manifest.judge_mode}` | **Guardrails**: `{manifest.guardrail_mode}`  ")
    lines.append(f"**Query Rewrite**: `{manifest.rewrite_mode}` | **Reranker**: `{manifest.reranker_provider}`  ")
    lines.append("")

    lines.append("## 1. System Reliability & Execution Status")
    lines.append("")
    lines.append("| Status Metric | Count / Value | Numerator / Denominator | Notes |")
    lines.append("| :--- | ---: | :---: | :--- |")

    tot = retrieval_summary.get("total_cases", 0)
    scored = retrieval_summary.get("scored_cases_count", 0)
    cov = retrieval_summary.get("coverage", 0.0)

    lines.append(f"| Scored Gold Coverage | {fmt_val(cov, is_pct=True)} | {scored}/{tot} | Cases with verified gold labels |")
    lines.append(f"| No Candidate Rate | {fmt_val(retrieval_summary.get('no_candidate_rate'), is_pct=True)} | {retrieval_summary.get('no_candidate_count', 0)}/{tot} | Empty candidate set |")
    lines.append(f"| Retrieval Error Rate | {fmt_val(retrieval_summary.get('retrieval_error_rate'), is_pct=True)} | {retrieval_summary.get('retrieval_error_count', 0)}/{tot} | Hybrid/FTS technical errors |")
    lines.append(f"| Reranker Error Rate | {fmt_val(retrieval_summary.get('reranker_error_rate'), is_pct=True)} | {retrieval_summary.get('reranker_error_count', 0)}/{tot} | Reranker API errors |")
    lines.append("")

    lines.append("## 2. Retrieval Quality Summary (Scored Cases)")
    lines.append("")
    lines.append("| Retrieval Metric | Value | Notes |")
    lines.append("| :--- | ---: | :--- |")

    doc_rec = retrieval_summary.get("doc_recall", {})
    art_rec = retrieval_summary.get("article_recall", {})
    cl_rec = retrieval_summary.get("clause_recall", {})

    lines.append(f"| Document Recall @ 1 | {fmt_val(doc_rec.get(1))} | Primary document candidate hit |")
    lines.append(f"| Document Recall @ 3 | {fmt_val(doc_rec.get(3))} | Top 3 document candidates |")
    lines.append(f"| Document Recall @ 5 | {fmt_val(doc_rec.get(5))} | Top 5 document candidates |")
    lines.append(f"| Document Recall @ 10 | {fmt_val(doc_rec.get(10))} | Top 10 document candidates |")
    lines.append(f"| Document Recall @ 24 | {fmt_val(doc_rec.get(24))} | Max document candidate pool |")
    lines.append(f"| Article Recall @ 1 | {fmt_val(art_rec.get(1))} | Top 1 article candidate |")
    lines.append(f"| Article Recall @ 3 | {fmt_val(art_rec.get(3))} | Top 3 article candidates |")
    lines.append(f"| Article Recall @ 6 | {fmt_val(art_rec.get(6))} | Top 6 article candidates |")
    lines.append(f"| Clause Recall @ 1 | {fmt_val(cl_rec.get(1))} | Top 1 clause candidate |")
    lines.append(f"| Clause Recall @ 3 | {fmt_val(cl_rec.get(3))} | Top 3 clause candidates |")
    lines.append(f"| Clause Recall @ 6 | {fmt_val(cl_rec.get(6))} | Top 6 clause candidates |")
    lines.append(f"| Article MRR | {fmt_val(retrieval_summary.get('mrr_article'))} | Mean Reciprocal Rank |")
    lines.append(f"| nDCG @ 10 | {fmt_val(retrieval_summary.get('ndcg_10'))} | Normalized DCG |")
    lines.append(f"| Exact Reference Hit Rate | {fmt_val(retrieval_summary.get('exact_reference_hit_rate'), is_pct=True)} | Exact citation match |")
    lines.append(f"| Multi-Hop All-Coverage | {fmt_val(retrieval_summary.get('all_hop_coverage_rate'), is_pct=True)} | All required evidence hits |")
    lines.append(f"| Multi-Hop Partial-Coverage | {fmt_val(retrieval_summary.get('partial_hop_coverage_rate'), is_pct=True)} | At least one required hit |")
    lines.append("")

    stage_metrics_map = retrieval_summary.get("stage_metrics", {})
    if stage_metrics_map:
        lines.append("### Stage-Specific Metric & Denominator Breakdown")
        lines.append("")
        lines.append("| Pipeline Stage | Stage Capacity | Scored Cases | Verified Gold Items | Recall@1 | Recall@3 | Recall@6 | Null Reason |")
        lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |")
        for stg_name, smetrics in stage_metrics_map.items():
            cap = smetrics.get("configured_stage_capacity", "N/A")
            sc_cases = smetrics.get("avg_scored_case_count", smetrics.get("scored_case_count", 0))
            v_items = smetrics.get("macro_verified_evidence_item_count", smetrics.get("verified_evidence_item_count", 0))
            r1 = smetrics.get("macro_doc_recall_at_1", smetrics.get("macro_article_recall_at_1", smetrics.get("doc_recall_at_1", smetrics.get("article_recall_at_1"))))
            r3 = smetrics.get("macro_doc_recall_at_3", smetrics.get("macro_article_recall_at_3", smetrics.get("doc_recall_at_3", smetrics.get("article_recall_at_3"))))
            r6 = smetrics.get("macro_doc_recall_at_6", smetrics.get("macro_article_recall_at_6", smetrics.get("doc_recall_at_6", smetrics.get("article_recall_at_6"))))
            null_rsn = smetrics.get("macro_article_recall_at_6_reason", smetrics.get("macro_doc_recall_at_6_reason", smetrics.get("article_recall_at_6_reason", smetrics.get("doc_recall_at_6_reason", "-"))))
            lines.append(
                f"| `{stg_name}` | {cap} | {sc_cases} | {v_items} | "
                f"{fmt_val(r1)} | {fmt_val(r3)} | {fmt_val(r6)} | `{null_rsn}` |"
            )
        lines.append("")

    fl_dist = retrieval_summary.get("first_loss_distribution", {})
    if fl_dist:
        lines.append("### First-Loss Stage Distribution (Gold Evidence Losses)")
        lines.append("")
        lines.append("| Pipeline Stage | Gold Items Lost First |")
        lines.append("| :--- | ---: |")
        for stg, count in fl_dist.items():
            lines.append(f"| `{stg}` | {count} |")
        lines.append("")

    if answer_summary:
        lines.append("## 3. Generation & Answer Accuracy Summary")
        lines.append("")
        lines.append("| Metric | Value | Notes |")
        lines.append("| :--- | ---: | :--- |")
        lines.append(f"| Answer Similarity Pass Rate | {fmt_val(answer_summary.get('answer_similarity_pass_rate'), is_pct=True)} | Token F1 >= 0.50 |")
        lines.append(f"| Unanswerable Accuracy | {fmt_val(answer_summary.get('unanswerable_accuracy'), is_pct=True)} | Honest refusal classification |")
        lines.append(f"| Refusal Precision | {fmt_val(answer_summary.get('refusal_precision'), is_pct=True)} | Correct refusals / Total predicted refusals |")
        lines.append(f"| Refusal Recall | {fmt_val(answer_summary.get('refusal_recall'), is_pct=True)} | Correct refusals / Unanswerable cases |")
        lines.append(f"| Token F1 | {fmt_val(answer_summary.get('token_f1'))} | Unigram token F1 |")
        lines.append(f"| Character F1 | {fmt_val(answer_summary.get('char_f1'))} | 3-gram character F1 |")
        lines.append(f"| ROUGE-L | {fmt_val(answer_summary.get('rouge_l'))} | Word LCS F1 |")
        lines.append(f"| CHRF | {fmt_val(answer_summary.get('chrf'))} | Character n-gram F-score |")
        lines.append(f"| Citation Precision | {fmt_val(answer_summary.get('citation_precision'))} | Valid citations / Total generated |")
        lines.append(f"| Invalid Citation Rate | {fmt_val(answer_summary.get('invalid_citation_rate'), is_pct=True)} | Hallucinated citations |")
        lines.append("")

    lines.append("## 4. Stage-Level Latency Breakdown")
    lines.append("")
    lines.append("| Stage / Operation | P50 (s) | P95 (s) | Mean (s) | Min (s) | Max (s) |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")

    for stage, stats in latency_summary.items():
        lines.append(
            f"| `{stage}` | {fmt_val(stats.get('p50'))}s | {fmt_val(stats.get('p95'))}s | "
            f"{fmt_val(stats.get('mean'))}s | {fmt_val(stats.get('min'))}s | {fmt_val(stats.get('max'))}s |"
        )
    lines.append("")

    if stage_survival_summary and "stage_statistics" in stage_survival_summary:
        lines.append("## 5. Stage-Level Candidate Survival & Retention")
        lines.append("")
        lines.append("| Retrieval Stage | Active Rate | Avg All | Avg Active | Min | P50 | P95 | Max |")
        lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        stats = stage_survival_summary.get("stage_statistics", {})
        for stage_name, sdict in stats.items():
            lines.append(
                f"| `{stage_name}` | {fmt_val(sdict.get('active_rate'), is_pct=True)} | "
                f"{sdict.get('mean_per_all_queries'):.2f} | {sdict.get('mean_per_active_query'):.2f} | "
                f"{sdict.get('min')} | {sdict.get('p50'):.2f} | {sdict.get('p95'):.2f} | {sdict.get('max')} |"
            )
        lines.append("")

    if case_results:
        lines.append("## 6. Case-by-Case Execution Details")
        lines.append("")
        lines.append("| Case ID | Group | Status | Latency | Article Recall | Token F1 | Refusal Category |")
        lines.append("| :---: | :--- | :--- | ---: | ---: | ---: | :--- |")
        for res in case_results:
            cid = res.get("case_id", "N/A")
            grp = res.get("question_type", "factoid")
            st = res.get("status", "ok")
            lat = res.get("latency", {}).get("t_total", res.get("latency", {}).get("t_retrieval", 0.0))
            m = res.get("metrics", {})
            art_rec_val = m.get("article_recall", {}).get(3, None) if isinstance(m.get("article_recall"), dict) else None
            art_rec_str = fmt_val(art_rec_val, decimals=2)
            tok_f1_val = m.get("token_f1", None)
            tok_f1_str = fmt_val(tok_f1_val, decimals=2)
            cat = res.get("refusal_category", "-")
            lines.append(f"| `{cid}` | {grp} | {st} | {fmt_val(lat, decimals=2)}s | {art_rec_str} | {tok_f1_str} | `{cat}` |")
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
