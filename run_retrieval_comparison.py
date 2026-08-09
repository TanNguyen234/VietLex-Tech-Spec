from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    write_immutable_json,
)
from app.evaluation.latency_metrics import calculate_stage_latency_summary
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.retrieval_metrics import (
    aggregate_retrieval_metrics,
    calculate_stage_survival_rates,
)
from app.evaluation.run_manifest import calculate_configuration_fingerprint
from app.evaluation.schemas import (
    EvaluationRunManifest,
    RetrievalAggregateMetrics,
    RetrievalCaseResult,
    RetrievalStageTrace,
)


PROJECT_ROOT = Path(__file__).resolve().parent
EXPECTED_PROFILES = {
    "legacy",
    "separated_no_intent",
    "separated_intent",
}
REQUIRED_RUN_FILES = (
    "manifest.json",
    "configuration.json",
    "evaluation_case_set.json",
    "retrieval_results.json",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and compare three immutable VietLex retrieval runs."
        )
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        required=True,
        help="Immutable retrieval run directory; specify exactly three times.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Repository-local immutable comparison output directory.",
    )
    return parser


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Required run artifact not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"Invalid JSON artifact {path}: {error}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_ids_sha256(case_ids: Sequence[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(case_ids),
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _matched_delta(
    before: Dict[str, int],
    after: Dict[str, int],
) -> Dict[str, int]:
    return {
        level: after.get(level, 0) - before.get(level, 0)
        for level in ("document", "article", "clause")
    }


def _load_verified_run(run_dir: Path) -> Dict[str, Any]:
    directory = Path(run_dir).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Run directory not found: {directory}")
    paths = {name: directory / name for name in REQUIRED_RUN_FILES}
    manifest = EvaluationRunManifest.model_validate(
        _load_json(paths["manifest.json"])
    )
    if manifest.git_dirty:
        raise ValueError(f"Run {manifest.run_id} is git-dirty")
    if manifest.provenance_status != "ok" or not manifest.source_state_sha256:
        raise ValueError(
            f"Run {manifest.run_id} has unavailable source provenance"
        )
    if manifest.eval_mode != "retrieval-only":
        raise ValueError(f"Run {manifest.run_id} is not retrieval-only")
    if manifest.judge_mode != "none" or manifest.guardrail_mode != "off":
        raise ValueError(
            f"Run {manifest.run_id} used a judge or guardrail mode"
        )

    configuration = _load_json(paths["configuration.json"])
    if configuration != manifest.configuration:
        raise ValueError(
            f"Run {manifest.run_id} configuration.json does not match manifest"
        )
    if (
        configuration.get("profile_name") != manifest.profile_name
        or configuration.get("profile", {}).get("name")
        != manifest.profile_name
    ):
        raise ValueError(
            f"Run {manifest.run_id} profile does not match configuration"
        )
    if (
        calculate_configuration_fingerprint(configuration)
        != manifest.configuration_fingerprint
    ):
        raise ValueError(
            f"Run {manifest.run_id} configuration fingerprint is invalid"
        )
    case_set = _load_json(paths["evaluation_case_set.json"])
    selected_ids = case_set.get("selected_case_ids")
    if not isinstance(selected_ids, list) or not all(
        isinstance(case_id, str) for case_id in selected_ids
    ):
        raise ValueError(f"Run {manifest.run_id} has invalid selected case IDs")
    selected_sha = _selected_ids_sha256(selected_ids)
    if selected_sha != case_set.get("selected_case_ids_sha256"):
        raise ValueError(
            f"Run {manifest.run_id} selected case IDs hash is invalid"
        )
    if (
        case_set.get("selected_case_count") != len(selected_ids)
        or manifest.selected_case_count != len(selected_ids)
        or manifest.selected_case_ids != selected_ids
        or manifest.selected_case_ids_sha256 != selected_sha
    ):
        raise ValueError(
            f"Run {manifest.run_id} case-set binding does not match manifest"
        )

    raw_results = _load_json(paths["retrieval_results.json"])
    if not isinstance(raw_results, list):
        raise ValueError(f"Run {manifest.run_id} results must be a list")
    results = [
        RetrievalCaseResult.model_validate(item).model_dump()
        for item in raw_results
    ]
    result_ids = [result["case_id"] for result in results]
    if result_ids != selected_ids or len(set(result_ids)) != len(result_ids):
        raise ValueError(
            f"Run {manifest.run_id} result case IDs do not match case set"
        )

    aggregate = aggregate_retrieval_metrics(results)
    RetrievalAggregateMetrics.model_validate(aggregate)
    if aggregate["metric_version"] != manifest.code_metric_version:
        raise ValueError(
            f"Run {manifest.run_id} metric version does not match manifest"
        )
    traces = [
        RetrievalStageTrace.model_validate(result["stage_trace"])
        for result in results
    ]
    latency = calculate_stage_latency_summary(
        [result["latency"] for result in results]
    )
    survival = calculate_stage_survival_rates(traces)
    stages = aggregate["stages"]
    source_stage = stages["source_retrieval_metrics"]
    reranker_input = stages["reranker_input_metrics"]["matched_gold_counts"]
    reranker_output = stages["reranker_output_metrics"]["matched_gold_counts"]
    input_total = sum(reranker_input.values())
    if input_total == 0:
        contribution_interpretation = (
            "not_measurable_no_verified_gold_at_reranker_input"
        )
    elif sum(reranker_output.values()) < input_total:
        contribution_interpretation = "reranker_lost_verified_gold"
    else:
        contribution_interpretation = "reranker_preserved_verified_gold"

    artifact_paths = list(paths.values())
    report_path = directory / "report.md"
    if report_path.is_file():
        artifact_paths.append(report_path)
    return {
        "manifest": manifest.model_dump(),
        "profile": {
            "run_id": manifest.run_id,
            "profile_name": manifest.profile_name,
            "configuration_fingerprint": manifest.configuration_fingerprint,
            "profile_configuration": configuration.get("profile", {}),
            "configured_provider_models": manifest.configured_provider_models,
            "command": manifest.command,
            "status_counts": dict(
                sorted(Counter(result["status"] for result in results).items())
            ),
            "technical_error_type_counts": dict(
                sorted(
                    Counter(
                        error_type
                        for result in results
                        for error_type in result["technical_errors"]
                    ).items()
                )
            ),
            "aggregate_metrics": aggregate,
            "latency": latency,
            "candidate_survival": survival,
            "initial_source_miss_evidence_count": (
                source_stage["applicable_gold_counts"]["document"]
                - source_stage["matched_gold_counts"]["document"]
            ),
            "first_loss_evidence_counts": {
                stage_name: stage["first_loss_evidence_count"]
                for stage_name, stage in stages.items()
            },
            "reranker_contribution": {
                "input_matched_gold_counts": reranker_input,
                "output_matched_gold_counts": reranker_output,
                "matched_gold_delta": _matched_delta(
                    reranker_input,
                    reranker_output,
                ),
                "interpretation": contribution_interpretation,
            },
            "artifact_sha256": {
                path.name: _sha256(path) for path in artifact_paths
            },
        },
    }


def _require_shared(
    loaded: Sequence[Dict[str, Any]],
    field: str,
) -> Any:
    values = [item["manifest"].get(field) for item in loaded]
    first = values[0]
    if any(value != first for value in values[1:]):
        raise ValueError(f"Run manifests disagree on {field}: {values}")
    return first


def _largest_defined_document_recall(profile: Dict[str, Any]) -> float:
    recalls = profile["aggregate_metrics"]["document_recall"]
    for k in sorted(recalls, key=int, reverse=True):
        value = recalls[k]["micro"]
        if value is not None:
            return float(value)
    return 0.0


def build_retrieval_comparison(
    run_dirs: Iterable[Path],
    *,
    comparison_provenance: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    directories = list(run_dirs)
    if len(directories) != 3:
        raise ValueError("Exactly three run directories are required")
    loaded = [_load_verified_run(path) for path in directories]
    by_profile: Dict[str, Dict[str, Any]] = {}
    for item in loaded:
        profile_name = item["manifest"]["profile_name"]
        if profile_name in by_profile:
            raise ValueError(f"Duplicate profile run: {profile_name}")
        by_profile[profile_name] = item["profile"]
    if set(by_profile) != EXPECTED_PROFILES:
        raise ValueError(
            f"Expected profiles {sorted(EXPECTED_PROFILES)}, got {sorted(by_profile)}"
        )

    shared_fields = (
        "git_sha",
        "source_state_sha256",
        "dataset_revision",
        "dataset_sha256",
        "evaluation_dataset_sha256",
        "gold_label_sidecar_sha256",
        "gold_policy",
        "selected_case_count",
        "selected_case_ids",
        "selected_case_ids_sha256",
        "code_metric_version",
        "configured_provider_models",
        "rewrite_mode",
        "reranker_provider",
        "eval_mode",
        "judge_mode",
        "guardrail_mode",
    )
    shared = {field: _require_shared(loaded, field) for field in shared_fields}
    max_recalls = {
        name: _largest_defined_document_recall(profile)
        for name, profile in by_profile.items()
    }
    if all(value == 0.0 for value in max_recalls.values()):
        decision_status = "NO_WINNER_ZERO_RECALL"
        recommended_profile = None
    else:
        best = max(max_recalls.values())
        winners = [name for name, value in max_recalls.items() if value == best]
        decision_status = (
            "WINNER_BY_MAX_DOCUMENT_RECALL"
            if len(winners) == 1
            else "NO_WINNER_TIED_MAX_DOCUMENT_RECALL"
        )
        recommended_profile = winners[0] if len(winners) == 1 else None

    payload: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": "COMPLETED",
        "decision_status": decision_status,
        "recommended_profile": recommended_profile,
        "shared_provenance": shared,
        "profiles": {
            name: by_profile[name] for name in sorted(by_profile)
        },
        "limitations": [
            (
                "Configured provider identifiers do not prove which fallback "
                "served a request because runtime provider diagnostics are not "
                "persisted in RetrievalCaseResult."
            ),
            (
                "The benchmark covers 40 curated all-required-verified cases "
                "from the 420-case evaluation dataset, not an independent "
                "sample of all 518,255 corpus documents."
            ),
        ],
    }
    if comparison_provenance is not None:
        payload["comparison_provenance"] = comparison_provenance
    return payload


def _metric(profile: Dict[str, Any], group: str, key: int | str) -> Dict[str, Any]:
    metrics = profile["aggregate_metrics"][group]
    return metrics.get(key, metrics.get(str(key)))


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _ratio_cell(metric: Dict[str, Any]) -> str:
    return (
        f"{_fmt(metric['micro'])} "
        f"({_fmt(metric['numerator'])}/{_fmt(metric['denominator'])})"
    )


def generate_markdown_comparison(comparison: Dict[str, Any]) -> str:
    shared = comparison["shared_provenance"]
    lines = [
        "# VietLex P2 Retrieval Profile Comparison",
        "",
        f"**Status:** `{comparison['status']}`  ",
        f"**Decision:** `{comparison['decision_status']}`  ",
        f"**Recommended profile:** `{comparison['recommended_profile'] or 'none'}`  ",
        f"**Run Git SHA:** `{shared['git_sha']}`  ",
        f"**Run source-state SHA-256:** `{shared['source_state_sha256']}`  ",
        f"**Dataset SHA-256:** `{shared['dataset_sha256']}`  ",
        f"**Gold sidecar SHA-256:** `{shared['gold_label_sidecar_sha256']}`  ",
        f"**Selected cases:** `{shared['selected_case_count']}`  ",
        f"**Selected-case-set SHA-256:** `{shared['selected_case_ids_sha256']}`  ",
        "",
        "## Quality and reliability",
        "",
        (
            "| Profile | Doc R@1 | Doc R@3 | Doc R@24 | Article R@3 | "
            "Clause R@3 | Doc MRR | nDCG@10 | Initial source misses | "
            "Statuses | Technical errors |"
        ),
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |",
    ]
    for name, profile in comparison["profiles"].items():
        aggregate = profile["aggregate_metrics"]
        lines.append(
            f"| `{name}` | "
            f"{_ratio_cell(_metric(profile, 'document_recall', 1))} | "
            f"{_ratio_cell(_metric(profile, 'document_recall', 3))} | "
            f"{_ratio_cell(_metric(profile, 'document_recall', 24))} | "
            f"{_ratio_cell(_metric(profile, 'article_recall', 3))} | "
            f"{_ratio_cell(_metric(profile, 'clause_recall', 3))} | "
            f"{_ratio_cell(aggregate['mrr']['document'])} | "
            f"{_ratio_cell(aggregate['ndcg_at_10'])} | "
            f"{profile['initial_source_miss_evidence_count']} | "
            f"{profile['status_counts']} | "
            f"{profile['technical_error_type_counts']} |"
        )

    lines.extend(
        [
            "",
            "## Coverage and secondary deterministic metrics",
            "",
            (
                "| Profile | Coverage | Exact reference | Multi-hop all | "
                "Multi-hop partial | No-candidate rate | Retrieval error rate | "
                "Reranker error rate | Scored / skipped | Skip reasons |"
            ),
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :--- |",
        ]
    )
    for name, profile in comparison["profiles"].items():
        aggregate = profile["aggregate_metrics"]
        lines.append(
            f"| `{name}` | {_ratio_cell(aggregate['coverage'])} | "
            f"{_ratio_cell(aggregate['exact_reference_hit'])} | "
            f"{_ratio_cell(aggregate['multi_hop_all_required'])} | "
            f"{_ratio_cell(aggregate['multi_hop_partial'])} | "
            f"{_ratio_cell(aggregate['no_candidate_rate'])} | "
            f"{_ratio_cell(aggregate['retrieval_technical_error_rate'])} | "
            f"{_ratio_cell(aggregate['reranker_technical_error_rate'])} | "
            f"{aggregate['scored_cases']} / {aggregate['skipped_cases']} | "
            f"{aggregate['skip_reason_counts']} |"
        )

    lines.extend(
        [
            "",
            "## Latency",
            "",
            "| Profile | Total mean (s) | Total p50 (s) | Total p95 (s) |",
            "| :--- | ---: | ---: | ---: |",
        ]
    )
    for name, profile in comparison["profiles"].items():
        total = profile["latency"]["t_total"]
        lines.append(
            f"| `{name}` | {_fmt(total['mean'])} | "
            f"{_fmt(total['p50'])} | {_fmt(total['p95'])} |"
        )

    lines.extend(["", "## Stage evidence losses", ""])
    for name, profile in comparison["profiles"].items():
        nonzero = {
            stage: count
            for stage, count in profile["first_loss_evidence_counts"].items()
            if count
        }
        reranker = profile["reranker_contribution"]
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- First-loss counts: `{nonzero or 'none'}`.",
                (
                    "- Reranker contribution: "
                    f"`{reranker['interpretation']}`; input matches "
                    f"`{reranker['input_matched_gold_counts']}`, output matches "
                    f"`{reranker['output_matched_gold_counts']}`."
                ),
                "",
            ]
        )

    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in comparison["limitations"])
    lines.extend(["", "## Run artifacts", ""])
    for name, profile in comparison["profiles"].items():
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- Run ID: `{profile['run_id']}`.",
                f"- Command: `{profile['command']}`.",
                f"- Artifact SHA-256: `{profile['artifact_sha256']}`.",
                f"- Configured providers: `{profile['configured_provider_models']}`.",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_immutable_text(path: Path, content: str) -> str:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8")
    try:
        file = target.open("xb")
    except FileExistsError:
        if target.read_bytes() == payload:
            return "reused"
        raise ArtifactCollisionError(
            f"Immutable text artifact collision: {target}"
        )
    try:
        with file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return "created"


def persist_comparison(output_dir: Path, comparison: Dict[str, Any]) -> Dict[str, str]:
    directory = Path(output_dir).resolve()
    return {
        "comparison.json": write_immutable_json(
            directory / "comparison.json",
            comparison,
        ),
        "report.md": _write_immutable_text(
            directory / "report.md",
            generate_markdown_comparison(comparison),
        ),
    }


def main(arguments: argparse.Namespace | None = None) -> int:
    args = arguments or build_parser().parse_args()
    output_dir = Path(args.output_dir).resolve()
    try:
        output_dir.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ValueError("--output-dir must remain inside the repository") from error
    provenance = collect_git_provenance(PROJECT_ROOT).model_dump()
    comparison = build_retrieval_comparison(
        args.run_dir,
        comparison_provenance=provenance,
    )
    persisted = persist_comparison(output_dir, comparison)
    print(json.dumps(persisted, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
