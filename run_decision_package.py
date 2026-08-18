from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evaluation.decision_package import build_decision_package
from app.evaluation.provenance import collect_git_provenance


DEFAULT_DATASET = Path("app/data/namsyntax_legal_qa_420_curated_v1.json")
DEFAULT_SIDECAR = Path(
    "docs/evaluation/adjudication/promotions/gold-adjudication-promotion-curated-v4_20260809_151015_227377/labels_v2.json"
)
DEFAULT_OUTPUT_DIR = Path("docs/evaluation/decision_packages")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Production-Light Decision Package across 4 evidence layers."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to evaluation dataset JSON.",
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=DEFAULT_SIDECAR,
        help="Path to gold sidecar labels JSON.",
    )
    parser.add_argument(
        "--production-benchmark-dir",
        type=Path,
        default=None,
        help="Optional path to deterministic production retrieval benchmark directory.",
    )
    parser.add_argument(
        "--online-snapshot",
        type=Path,
        default=None,
        help="Optional path to online interaction logs snapshot JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for decision package artifacts.",
    )
    parser.add_argument(
        "--package-id",
        type=str,
        default=None,
        help="Optional package ID string. If omitted, deterministically derived from inputs.",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Require clean git working tree before building decision package.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.require_clean_git:
        prov = collect_git_provenance()
        if prov.git_dirty:
            print(
                f"ERROR: Git working tree is dirty (SHA: {prov.git_sha[:8]}, diff: {prov.git_diff_status}). "
                "--require-clean-git specified.",
                file=sys.stderr,
            )
            return 1

    if not args.dataset.exists():
        print(f"ERROR: Dataset file not found: {args.dataset}", file=sys.stderr)
        return 1

    if not args.sidecar.exists():
        print(f"ERROR: Sidecar file not found: {args.sidecar}", file=sys.stderr)
        return 1

    if args.production_benchmark_dir and not args.production_benchmark_dir.exists():
        print(
            f"ERROR: Production benchmark directory not found: {args.production_benchmark_dir}",
            file=sys.stderr,
        )
        return 1

    if args.online_snapshot and not args.online_snapshot.exists():
        print(
            f"ERROR: Online snapshot file not found: {args.online_snapshot}",
            file=sys.stderr,
        )
        return 1

    res = build_decision_package(
        dataset_path=args.dataset,
        sidecar_path=args.sidecar,
        output_dir=args.output_dir,
        production_benchmark_dir=args.production_benchmark_dir,
        online_snapshot_path=args.online_snapshot,
        package_id=args.package_id,
    )

    verdict = res.decision_dict.get("production_readiness", {}).get("status", "UNKNOWN")
    print(f"Package ID: {res.package_id}")
    print(f"Write Status: {res.write_status}")
    print(f"Decision JSON: {res.decision_file}")
    print(f"Report Markdown: {res.report_file}")
    print(f"Production Readiness Verdict: {verdict}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
