from __future__ import annotations

import hashlib
import json
from typing import Sequence

from pydantic import BaseModel

from app.ingestion.legal_text import EvidenceChunk


def _sha(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CandidatePoolEntry(BaseModel):
    candidate_id: str
    document_id: int
    document_number: str
    article: str | None
    clause: str | None
    citation: str
    text_sha256: str
    rank: int
    score: float | None = None


class CandidatePool(BaseModel):
    case_id: str
    backend_contract_sha256: str
    candidates: list[CandidatePoolEntry]
    candidate_ids_sha256: str
    candidate_payload_sha256: str


def build_candidate_pool(
    case_id: str,
    evidence: Sequence[EvidenceChunk],
    backend_contract: str,
    scores: Sequence[float | None] | None = None,
) -> CandidatePool:
    if scores is not None and len(scores) != len(evidence):
        raise ValueError("candidate scores must align with evidence")
    entries = []
    for rank, item in enumerate(evidence, start=1):
        text_sha = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
        identity = _sha(
            [item.document_id, item.citation, text_sha]
        )
        entries.append(
            CandidatePoolEntry(
                candidate_id=identity,
                document_id=item.document_id,
                document_number=item.document_number,
                article=item.article,
                clause=item.clause,
                citation=item.citation,
                text_sha256=text_sha,
                rank=rank,
                score=scores[rank - 1] if scores is not None else None,
            )
        )
    payload = [entry.model_dump(mode="json") for entry in entries]
    return CandidatePool(
        case_id=case_id,
        backend_contract_sha256=_sha(backend_contract),
        candidates=entries,
        candidate_ids_sha256=_sha([entry.candidate_id for entry in entries]),
        candidate_payload_sha256=_sha(payload),
    )


def assert_identical_candidate_pool(
    expected: CandidatePool,
    actual: CandidatePool,
) -> None:
    if (
        expected.backend_contract_sha256 != actual.backend_contract_sha256
        or expected.candidate_ids_sha256 != actual.candidate_ids_sha256
        or expected.candidate_payload_sha256 != actual.candidate_payload_sha256
    ):
        raise ValueError("candidate pool identity mismatch")
