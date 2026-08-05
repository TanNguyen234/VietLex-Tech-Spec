from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.evaluation.schemas import GoldEvidence, GoldenCase


class CaseSelectionResult(BaseModel):
    gold_policy: str
    selected_cases: List[GoldenCase] = Field(default_factory=list)
    selected_case_ids: List[str] = Field(default_factory=list)
    selected_case_ids_sha256: str = ""
    total_candidate_cases: int = 0
    selected_case_count: int = 0
    answerable_selected_count: int = 0
    fully_verified_factoid_count: int = 0
    fully_verified_multihop_count: int = 0
    partial_verified_multihop_count: int = 0
    excluded_unanswerable_count: int = 0
    excluded_no_verified_label_count: int = 0
    verified_evidence_item_count: int = 0
    status_breakdown: Dict[str, int] = Field(default_factory=dict)


def build_cases(
    raw_dataset: List[Dict[str, Any]],
    labels_by_case_id: Dict[str, List[GoldEvidence]],
) -> List[GoldenCase]:
    cases: List[GoldenCase] = []
    for idx, raw_case in enumerate(raw_dataset, start=1):
        case_id = raw_case.get("case_id", f"case_{idx:03d}")
        q_text = raw_case.get("question", "").strip()
        q_type = raw_case.get("question_type", "factoid")
        gt_ans = raw_case.get("ground_truth_answer", "").strip()
        gt_contexts = raw_case.get("ground_truth_context", [])

        is_unanswerable = (
            q_type == "unanswerable"
            or "tài liệu không đề cập" in gt_ans.casefold()
        )

        case_evidence = labels_by_case_id.get(case_id, [])

        case_obj = GoldenCase(
            case_id=case_id,
            question=q_text,
            question_type=q_type,
            answerable=not is_unanswerable,
            reference_answer=gt_ans,
            reference_contexts=gt_contexts,
            gold_evidence=case_evidence,
            expected_numbers=raw_case.get("expected_numbers", []),
            expected_dates=raw_case.get("expected_dates", []),
            expected_entities=raw_case.get("expected_entities", []),
        )
        cases.append(case_obj)
    return cases


def select_evaluation_cases(
    cases: List[GoldenCase],
    gold_policy: str,
    include_unanswerable: bool = False,
    limit: Optional[int] = None,
) -> CaseSelectionResult:
    selected_cases: List[GoldenCase] = []
    selected_case_ids: List[str] = []

    fully_verified_factoid = 0
    fully_verified_multihop = 0
    partial_verified_multihop = 0
    excluded_unanswerable = 0
    excluded_no_verified = 0
    verified_evidence_count = 0
    status_counts: Dict[str, int] = {}

    for case in cases:
        if not case.answerable and not include_unanswerable:
            excluded_unanswerable += 1
            status_counts["excluded_unanswerable"] = status_counts.get("excluded_unanswerable", 0) + 1
            continue

        verified_labels = [g for g in case.gold_evidence if g.status == "verified"]
        required_labels = [g for g in case.gold_evidence if g.required]
        required_verified = [g for g in required_labels if g.status == "verified"]

        is_selected = False

        if gold_policy == "all-required-verified":
            # Mandatory Fix: len(required_labels) > 0 prevent all([]) == True bug!
            if (
                case.answerable
                and len(required_labels) > 0
                and len(required_verified) == len(required_labels)
            ):
                is_selected = True

        elif gold_policy == "any-verified":
            if case.answerable and len(verified_labels) > 0:
                is_selected = True

        elif gold_policy == "all-verified":
            if (
                case.answerable
                and len(case.gold_evidence) > 0
                and len(verified_labels) == len(case.gold_evidence)
            ):
                is_selected = True

        elif gold_policy == "none":
            is_selected = case.answerable or include_unanswerable
        else:
            raise ValueError(f"Unknown gold_policy: '{gold_policy}'")

        if is_selected:
            selected_cases.append(case)
            selected_case_ids.append(case.case_id)
            verified_evidence_count += len(verified_labels)
            if limit and len(selected_cases) >= limit:
                break

            if len(required_labels) > 0 and len(required_verified) == len(required_labels):
                if case.question_type == "multi-hop":
                    fully_verified_multihop += 1
                else:
                    fully_verified_factoid += 1
            elif case.question_type == "multi-hop" and len(verified_labels) > 0:
                partial_verified_multihop += 1

            status_counts["selected"] = status_counts.get("selected", 0) + 1
        else:
            excluded_no_verified += 1
            status_counts["excluded_no_verified_label"] = status_counts.get("excluded_no_verified_label", 0) + 1

    # Stable canonical JSON serialization SHA-256
    canonical_json = json.dumps(selected_case_ids, separators=(",", ":"))
    sha256_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return CaseSelectionResult(
        gold_policy=gold_policy,
        selected_cases=selected_cases,
        selected_case_ids=selected_case_ids,
        selected_case_ids_sha256=sha256_hash,
        total_candidate_cases=len(cases),
        selected_case_count=len(selected_cases),
        answerable_selected_count=sum(1 for c in selected_cases if c.answerable),
        fully_verified_factoid_count=fully_verified_factoid,
        fully_verified_multihop_count=fully_verified_multihop,
        partial_verified_multihop_count=partial_verified_multihop,
        excluded_unanswerable_count=excluded_unanswerable,
        excluded_no_verified_label_count=excluded_no_verified,
        verified_evidence_item_count=verified_evidence_count,
        status_breakdown=status_counts,
    )
