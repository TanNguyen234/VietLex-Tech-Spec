"""Provider-free batching for explicit full-document contract reviews."""

from __future__ import annotations

import hashlib
import json

from app.config import get_settings


PLAN_VERSION = "full-document-review-v1"


def _tokens(value: str) -> int:
    return len(value.split())


def _fits_contract_review(
    clauses: list[dict], evidence: list[dict], budget: int
) -> bool:
    blocks = [
        f"[CONTRACT {item.get('clause_id', '')}] {str(item.get('title') or '')[:240]}\n{str(item.get('text') or '')}"
        for item in clauses
    ] + [
        f"[LAW {item.get('evidence_id', '')}] {str(item.get('citation') or '')[:300]}\n{str(item.get('excerpt') or item.get('original') or '')}"
        for item in evidence
    ]
    return (
        sum(_tokens(block) for block in blocks) <= budget
        and sum(map(len, blocks)) <= 20_000
    )


def _fingerprint(document: dict, evidence: list[dict]) -> str:
    payload = {
        "document_id": document.get("document_id"),
        "clauses": [
            {
                "clause_id": item.get("clause_id"),
                "title": item.get("title"),
                "text": item.get("text"),
            }
            for item in document.get("clauses") or []
        ],
        "evidence": [
            {
                "evidence_id": item.get("evidence_id"),
                "citation": item.get("citation"),
                "excerpt": item.get("excerpt"),
                "original": item.get("original"),
            }
            for item in evidence
        ],
    }
    payload["plan_version"] = PLAN_VERSION
    payload["context_budget"] = get_settings().LLM_CONTEXT_MAX_TOKENS
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def plan_full_document_review(document: dict, legal_evidence: list[dict]) -> dict:
    """Make bounded, deterministic batches; oversized clauses are never omitted silently."""
    clauses = list(document.get("clauses") or [])
    if not clauses or len(clauses) > 100:
        raise ValueError("invalid_document_clauses")
    if len(legal_evidence) > 10:
        raise ValueError("evidence_scope_too_large")
    budget = get_settings().LLM_CONTEXT_MAX_TOKENS
    batches: list[dict] = []
    skipped: list[dict] = []
    current: list[dict] = []
    current_tokens = 0
    for clause in clauses:
        clause_tokens = _tokens(str(clause.get("title") or "")) + _tokens(
            str(clause.get("text") or "")
        )
        clause_id = str(clause.get("clause_id") or "")
        if not clause_id or not str(clause.get("text") or ""):
            skipped.append({"clause_id": clause_id, "reason": "invalid_clause"})
        elif not _fits_contract_review([clause], legal_evidence, budget):
            skipped.append(
                {"clause_id": clause_id, "reason": "clause_exceeds_context_budget"}
            )
        else:
            if current and (
                len(current) == 10
                or not _fits_contract_review(current + [clause], legal_evidence, budget)
            ):
                batches.append(
                    {
                        "batch_id": f"batch-{len(batches) + 1}",
                        "clause_ids": [str(x["clause_id"]) for x in current],
                    }
                )
                current, current_tokens = [], 0
            current.append(clause)
            current_tokens += clause_tokens
    if current:
        batches.append(
            {
                "batch_id": f"batch-{len(batches) + 1}",
                "clause_ids": [str(x["clause_id"]) for x in current],
            }
        )
    scheduled = sum(len(item["clause_ids"]) for item in batches)
    input_sha256 = _fingerprint(document, legal_evidence)
    stored_progress = next(
        (
            item
            for item in document.get("full_review_progress") or []
            if item.get("input_sha256") == input_sha256
        ),
        {},
    )
    completed = set(stored_progress.get("completed_clause_ids") or [])
    return {
        "status": "ready" if not skipped else "review_incomplete",
        "document_id": str(document.get("document_id") or ""),
        "input_sha256": input_sha256,
        "completed_clause_ids": sorted(completed),
        "legal_evidence_ids": [
            str(item.get("evidence_id") or "") for item in legal_evidence
        ],
        "batches": batches,
        "skipped": skipped,
        "coverage": {
            "total_clauses": len(clauses),
            "scheduled_clauses": scheduled,
            "reviewed_clauses": len(completed),
            "pending_clauses": max(0, scheduled - len(completed)),
            "skipped_clauses": len(skipped),
            "complete": False,
        },
    }


def aggregate_full_document_review(plan: dict, analyses: list[dict]) -> dict:
    scheduled = {item for batch in plan["batches"] for item in batch["clause_ids"]}
    reviewed = set(plan.get("completed_clause_ids") or []) | {
        clause_id
        for analysis in analyses
        if analysis.get("kind") == "full_document_review"
        and analysis.get("document_id") == plan["document_id"]
        and analysis.get("input_sha256") == plan["input_sha256"]
        and analysis.get("status") == "ok"
        for clause_id in analysis.get("clause_ids") or []
    }
    coverage = {
        **plan["coverage"],
        "reviewed_clauses": len(reviewed & scheduled),
        "pending_clauses": len(scheduled - reviewed),
    }
    coverage["complete"] = (
        not coverage["pending_clauses"] and not coverage["skipped_clauses"]
    )
    return {
        "status": "complete" if coverage["complete"] else "review_incomplete",
        "coverage": coverage,
        "pending_batch_ids": [
            batch["batch_id"]
            for batch in plan["batches"]
            if set(batch["clause_ids"]) - reviewed
        ],
        "skipped": plan["skipped"],
    }
