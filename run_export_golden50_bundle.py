from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.golden_bundle import export_golden_subset
from run_retrieval_eval import DEFAULT_DATASET_PATH, DEFAULT_SIDECAR_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export an independently runnable, readable golden subset."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR_PATH)
    parser.add_argument("--case-set", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evaluation/golden50-v3"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    case_set = json.loads(args.case_set.read_text(encoding="utf-8"))
    report = export_golden_subset(
        dataset_path=args.dataset,
        sidecar_path=args.sidecar,
        selected_case_ids=case_set["selected_case_ids"],
        output_dir=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
