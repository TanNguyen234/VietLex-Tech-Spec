from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class GoldEvidence(BaseModel):
    document_id: Optional[Union[int, str]] = None
    document_number: Optional[str] = None
    article: Optional[str] = None
    clause: Optional[str] = None
    required: bool = True
    status: str = "verified"  # "verified" | "missing_gold_label"


class GoldenCase(BaseModel):
    case_id: str
    question: str
    question_type: str  # "factoid" | "multi-hop" | "unanswerable"
    answerable: bool
    reference_answer: str
    reference_contexts: List[str] = Field(default_factory=list)
    gold_evidence: List[GoldEvidence] = Field(default_factory=list)
    expected_numbers: List[str] = Field(default_factory=list)
    expected_dates: List[str] = Field(default_factory=list)
    expected_entities: List[str] = Field(default_factory=list)


class CandidateChunk(BaseModel):
    document_id: int
    document_number: str
    title: str
    source_url: str
    citation: str
    article: Optional[str] = None
    clause: Optional[str] = None
    text: str
    token_count: int
    score: Optional[float] = None


class RetrievalStageTrace(BaseModel):
    pinecone_hits: List[Dict[str, Any]] = Field(default_factory=list)
    lexical_hits: List[int] = Field(default_factory=list)
    merged_document_ids: List[int] = Field(default_factory=list)
    resolved_document_ids: List[int] = Field(default_factory=list)
    locally_selected_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    reranker_input_chunks: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    reranker_output_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    final_evidence_chunks: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)


class RetrievalCaseResult(BaseModel):
    case_id: str
    question: str
    question_type: str
    answerable: bool
    query_used: str
    original_query: str
    rewritten_query: Optional[str] = None
    status: str  # "ok", "no_candidate", "retrieval_error", "reranker_error"
    retrieved_evidence: List[CandidateChunk] = Field(default_factory=list)
    stage_trace: RetrievalStageTrace = Field(default_factory=RetrievalStageTrace)
    latency: Dict[str, float] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AnswerCaseResult(BaseModel):
    case_id: str
    question: str
    question_type: str
    answerable: bool
    retrieval_result: RetrievalCaseResult
    raw_response: str
    final_response: str
    input_safe: bool = True
    output_safe: bool = True
    refusal_category: str  # "pure_refusal" | "disclaimer" | "mixed_claim_refusal" | "technical_error" | "no_evidence" | "normal_answer"
    latency: Dict[str, float] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    ragas_metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class EvaluationRunManifest(BaseModel):
    run_id: str
    utc_timestamp: str
    git_sha: str
    dataset_revision: str
    dataset_sha256: str
    configuration_fingerprint: str
    command: str
    eval_mode: str  # "retrieval-only" | "answer"
    judge_mode: str  # "none" | "ragas"
    guardrail_mode: str  # "off" | "shadow" | "enforce"
    rewrite_mode: str  # "off" | "on"
    reranker_provider: str  # "current" | "pinecone-bge" | "qdrant-colbert"
    configuration: Dict[str, Any] = Field(default_factory=dict)
    code_metric_version: str = "1.0.0"
