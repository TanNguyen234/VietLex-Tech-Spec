from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class EvaluationProfile:
    name: str
    retrieval_document_limit: int = 24
    resolved_document_limit: int = 16
    local_chunks_per_document: int = 4
    rerank_input_limit: int = 24
    rerank_return_limit: int = 3
    final_evidence_limit: int = 3
    final_context_token_limit: int = 720
    intent_scoring_enabled: bool = True
    rewrite_mode: str = "off"
    reranker_mode: str = "current"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "retrieval_document_limit": self.retrieval_document_limit,
            "resolved_document_limit": self.resolved_document_limit,
            "local_chunks_per_document": self.local_chunks_per_document,
            "rerank_input_limit": self.rerank_input_limit,
            "rerank_return_limit": self.rerank_return_limit,
            "final_evidence_limit": self.final_evidence_limit,
            "final_context_token_limit": self.final_context_token_limit,
            "intent_scoring_enabled": self.intent_scoring_enabled,
            "rewrite_mode": self.rewrite_mode,
            "reranker_mode": self.reranker_mode,
        }


PROFILES: Dict[str, EvaluationProfile] = {
    "legacy": EvaluationProfile(
        name="legacy",
        retrieval_document_limit=24,
        resolved_document_limit=12,
        local_chunks_per_document=2,
        rerank_input_limit=12,
        rerank_return_limit=3,
        final_evidence_limit=3,
        intent_scoring_enabled=False,
    ),
    "separated_no_intent": EvaluationProfile(
        name="separated_no_intent",
        retrieval_document_limit=24,
        resolved_document_limit=16,
        local_chunks_per_document=4,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
        intent_scoring_enabled=False,
    ),
    "separated_intent": EvaluationProfile(
        name="separated_intent",
        retrieval_document_limit=24,
        resolved_document_limit=16,
        local_chunks_per_document=4,
        rerank_input_limit=24,
        rerank_return_limit=3,
        final_evidence_limit=3,
        intent_scoring_enabled=True,
    ),
}


def get_evaluation_profile(profile_name: str) -> EvaluationProfile:
    if profile_name in PROFILES:
        return PROFILES[profile_name]
    raise ValueError(f"Unknown evaluation profile '{profile_name}'. Available: {list(PROFILES.keys())}")
