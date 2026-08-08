from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from app.evaluation.schemas import (
    EvaluationRunManifest,
    EvaluationSchemaError,
    RetrievalAggregateMetrics,
)


def fmt_val(v: Any, is_pct: bool = False, decimals: int = 4) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, (int, float)):
        if is_pct:
            return f"{v * 100:.1f}%"
        return f"{v:.{decimals}f}"
    return str(v)


def fmt_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(
        f"{key}={value}" for key, value in sorted(counts.items())
    )


def generate_markdown_report(
    manifest: EvaluationRunManifest,
    retrieval_summary: Dict[str, Any],
    stage_survival_summary: Dict[str, Any],
    latency_summary: Dict[str, Dict[str, float]],
    answer_summary: Optional[Dict[str, Any]] = None,
    case_results: List[Dict[str, Any]] = None,
) -> str:
    try:
        summary = RetrievalAggregateMetrics.model_validate(
            retrieval_summary
        )
    except ValidationError as error:
        raise EvaluationSchemaError(
            "invalid aggregate retrieval metric schema"
        ) from error

    lines: List[str] = [
        f"# VIETLEX EVALUATION REPORT — {manifest.run_id}",
        "",
        f"**Run ID**: `{manifest.run_id}`  ",
        f"**Profile**: `{manifest.profile_name}`  ",
        f"**UTC Timestamp**: `{manifest.utc_timestamp}`  ",
        f"**Git Commit SHA**: `{manifest.git_sha}`  ",
        (
            "**Source State SHA-256**: "
            f"`{manifest.source_state_sha256 or 'unavailable'}`  "
        ),
        (
            "**Git Dirty Status**: "
            f"`{manifest.git_dirty}` "
            f"(Diff: `{manifest.git_diff_status}`, "
            f"SHA-256: `{manifest.git_diff_sha256 or 'N/A'}`)  "
        ),
        f"**Dataset Revision**: `{manifest.dataset_revision}`  ",
        f"**Dataset SHA-256**: `{manifest.dataset_sha256}`  ",
        (
            "**Configuration Fingerprint**: "
            f"`{manifest.configuration_fingerprint}`  "
        ),
        f"**Execution Command**: `{manifest.command}`  ",
        (
            f"**Evaluation Mode**: `{manifest.eval_mode}` | "
            f"**Judge**: `{manifest.judge_mode}` | "
            f"**Guardrails**: `{manifest.guardrail_mode}`  "
        ),
        "",
        f"Metric schema: `{summary.metric_version}`",
        f"Scored / Total: `{summary.scored_cases} / {summary.total_cases}`",
        f"Skipped cases: `{summary.skipped_cases}`",
        f"Skip reasons: `{fmt_counts(summary.skip_reason_counts)}`",
        "",
        "## 1. Reliability and coverage",
        "",
        (
            "| Metric | Macro | Micro | Numerator / Denominator | "
            "Scored / Skipped | Skip reasons | Notes |"
        ),
        "| :--- | ---: | ---: | :---: | :---: | :--- | :--- |",
    ]

    def append_metric(
        label: str,
        metric: Any,
        notes: str,
        *,
        percentage: bool = False,
    ) -> None:
        lines.append(
            f"| {label} | {fmt_val(metric.macro, is_pct=percentage)} | "
            f"{fmt_val(metric.micro, is_pct=percentage)} | "
            f"{fmt_val(metric.numerator)}/{fmt_val(metric.denominator)} | "
            f"{metric.scored_cases} / {metric.skipped_cases} | "
            f"{fmt_counts(metric.skip_reasons)} | "
            f"{notes} |"
        )

    append_metric(
        "Scored gold coverage",
        summary.coverage,
        "Cases with applicable verified required evidence",
        percentage=True,
    )
    append_metric(
        "No-candidate rate",
        summary.no_candidate_rate,
        "Completed retrievals with zero candidates",
        percentage=True,
    )
    append_metric(
        "Retrieval technical-error rate",
        summary.retrieval_technical_error_rate,
        "Exact status retrieval_error",
        percentage=True,
    )
    append_metric(
        "Reranker technical-error rate",
        summary.reranker_technical_error_rate,
        "Exact status reranker_error",
        percentage=True,
    )

    lines.extend(
        [
            "",
            "## 2. Retrieval quality",
            "",
            (
                "| Metric | Macro | Micro | Numerator / Denominator | "
                "Scored / Skipped | Skip reasons |"
            ),
            "| :--- | ---: | ---: | :---: | :---: | :--- |",
        ]
    )

    def append_quality(label: str, metric: Any) -> None:
        lines.append(
            f"| {label} | {fmt_val(metric.macro)} | "
            f"{fmt_val(metric.micro)} | "
            f"{fmt_val(metric.numerator)}/{fmt_val(metric.denominator)} | "
            f"{metric.scored_cases} / {metric.skipped_cases} | "
            f"{fmt_counts(metric.skip_reasons)} |"
        )

    for k, metric in sorted(summary.document_recall.items()):
        append_quality(f"Document Recall @ {k}", metric)
    for k, metric in sorted(summary.article_recall.items()):
        append_quality(f"Article Recall @ {k}", metric)
    for k, metric in sorted(summary.clause_recall.items()):
        append_quality(f"Clause Recall @ {k}", metric)
    for level, metric in sorted(summary.mrr.items()):
        append_quality(f"{level.title()} MRR", metric)
    append_quality("nDCG @ 10", summary.ndcg_at_10)
    append_quality("Exact legal-reference hit", summary.exact_reference_hit)
    append_quality(
        "Multi-hop all-required coverage",
        summary.multi_hop_all_required,
    )
    append_quality(
        "Multi-hop partial coverage",
        summary.multi_hop_partial,
    )

    if summary.stages:
        lines.extend(
            [
                "",
                "## 3. Stage metrics",
                "",
                (
                    "| Pipeline stage | Capacity | Scored cases | "
                    "Candidate p50 / p95 | Matched / Applicable "
                    "documents | First-loss evidence count | Null reasons |"
                ),
                "| :--- | ---: | ---: | :---: | :---: | ---: | :--- |",
            ]
        )
        for stage_name, stage in summary.stages.items():
            matched = stage.matched_gold_counts.get("document", 0)
            applicable = stage.applicable_gold_counts.get(
                "document", 0
            )
            lines.append(
                f"| `{stage_name}` | "
                f"{stage.configured_capacity if stage.configured_capacity is not None else 'N/A'} | "
                f"{stage.scored_case_count} | "
                f"{fmt_val(stage.candidates.p50)} / "
                f"{fmt_val(stage.candidates.p95)} | "
                f"{matched} / {applicable} | "
                f"{stage.first_loss_evidence_count} | "
                f"{fmt_counts(stage.null_reason_counts)} |"
            )

    lines.extend(
        [
            "",
            "## 4. Interpretation notes",
            "",
            (
                "- Recall@K is undefined when K exceeds the configured "
                "stage capacity; nDCG@10 still treats unreturned ranks as "
                "zero gain so capacity effects remain measurable."
            ),
            (
                "- Configured provider candidates are provenance only; "
                "they do not prove which provider answered a request."
            ),
        ]
    )

    if answer_summary:
        lines.extend(
            [
                "",
                "## 5. Deterministic answer metrics",
                "",
                (
                    "Answer scored / total: "
                    f"`{answer_summary.get('scored_cases', 0)} / "
                    f"{answer_summary.get('total_cases', 0)}`"
                ),
                (
                    "Answer skip reasons: `"
                    f"{fmt_counts(answer_summary.get('skip_reason_counts', {}))}`"
                ),
                "",
                "| Metric | Value |",
                "| :--- | ---: |",
            ]
        )
        for key in (
            "answer_similarity_pass_rate",
            "unanswerable_accuracy",
            "refusal_precision",
            "refusal_recall",
            "token_f1",
            "char_f1",
            "rouge_l",
            "chrf",
            "citation_precision",
            "invalid_citation_rate",
        ):
            lines.append(
                f"| `{key}` | {fmt_val(answer_summary.get(key))} |"
            )

    if latency_summary:
        lines.extend(
            [
                "",
                "## 6. Latency",
                "",
                "| Stage | P50 (s) | P95 (s) | Mean (s) |",
                "| :--- | ---: | ---: | ---: |",
            ]
        )
        for stage, stats in latency_summary.items():
            lines.append(
                f"| `{stage}` | {fmt_val(stats.get('p50'))} | "
                f"{fmt_val(stats.get('p95'))} | "
                f"{fmt_val(stats.get('mean'))} |"
            )

    if stage_survival_summary:
        lines.extend(
            [
                "",
                "## 7. Runtime candidate trace summary",
                "",
                (
                    "The runtime trace summary is diagnostic only; "
                    "quality denominators come from the validated v3 "
                    "metric contract above."
                ),
            ]
        )

    if case_results:
        lines.extend(
            [
                "",
                "## 8. Case statuses",
                "",
                "| Case ID | Status | Total latency (s) |",
                "| :--- | :--- | ---: |",
            ]
        )
        for result in case_results:
            lines.append(
                f"| `{result.get('case_id', 'N/A')}` | "
                f"`{result.get('status', 'unknown')}` | "
                f"{fmt_val(result.get('latency', {}).get('t_total'))} |"
            )

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
