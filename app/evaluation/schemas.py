from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    DOCUMENT_VERIFIED_ARTICLE_UNRESOLVED = "document_verified_article_unresolved"
    ARTICLE_VERIFIED_CLAUSE_UNRESOLVED = "article_verified_clause_unresolved"
    STRUCTURAL_ANCHOR_NOT_FOUND = "structural_anchor_not_found"
    NO_CITATION_EXTRACTED = "no_citation_extracted"
    UNANSWERABLE = "unanswerable"
    NOT_FOUND_BY_LOCAL_DETERMINISTIC_AUDIT = "not_found_by_local_deterministic_audit"
    AMBIGUOUS = "ambiguous"


class RequiredLevel(str, Enum):
    DOCUMENT = "document"
    ARTICLE = "article"
    CLAUSE = "clause"


class GoldEvidence(BaseModel):
    evidence_item_id: str
    case_id: str
    context_index: int = 0
    citation_index: int = 0
    reference_anchor_hash: Optional[str] = None
    document_id: Optional[Union[int, str]] = None
    document_number: Optional[str] = None
    article: Optional[str] = None
    clause: Optional[str] = None
    required: bool
    required_level: RequiredLevel = RequiredLevel.ARTICLE
    status: EvidenceStatus
    verification_confidence: Optional[str] = None
    candidate_generation_method: Optional[str] = None
    document_identity_method: Optional[str] = None
    candidate_count_before_anchor: Optional[int] = None
    corpus_search_limit: Optional[int] = None
    anchor_match_method: Optional[str] = None
    identity_hint_sources: List[str] = Field(default_factory=list)
    is_metadata_search_complete: bool = False


class RetrievalStageCapacities(BaseModel):
    pinecone_document_limit: Optional[int] = 24
    fts_document_limit: Optional[int] = 24
    merged_document_limit: Optional[int] = 24
    resolved_document_limit: Optional[int] = 16
    structural_chunk_limit: Optional[int] = 64
    local_chunks_limit: Optional[int] = 4
    rerank_input_limit: Optional[int] = 24
    rerank_return_limit: Optional[int] = 12
    final_evidence_limit: Optional[int] = 3


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


class StageCandidate(BaseModel):
    document_id: Optional[Union[int, str]] = None
    document_number: Optional[str] = None
    title: Optional[str] = None
    source_url: Optional[str] = None
    citation: Optional[str] = None
    article: Optional[str] = None
    clause: Optional[str] = None
    text: Optional[str] = None
    score: Optional[float] = None
    source: str = "unknown"  # "pinecone" | "fts" | "merged" | "resolved" | "structural" | "local" | "reranker" | "final"


class RetrievalStageTrace(BaseModel):
    pinecone_hits: List[StageCandidate] = Field(default_factory=list)
    fts_hits: List[StageCandidate] = Field(default_factory=list)
    merged_document_candidates: List[StageCandidate] = Field(default_factory=list)
    resolved_document_candidates: List[StageCandidate] = Field(default_factory=list)
    structural_chunks_generated: List[StageCandidate] = Field(default_factory=list)
    locally_selected_chunks: List[StageCandidate] = Field(default_factory=list)
    reranker_input_chunks: List[StageCandidate] = Field(default_factory=list)
    reranker_output_chunks: List[StageCandidate] = Field(default_factory=list)
    final_evidence_chunks: List[StageCandidate] = Field(default_factory=list)


class RatioMetricV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: float
    denominator: float
    value: Optional[float] = None
    reason: Optional[str] = None


class MultiHopCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_required: bool
    matched_required_items: int
    required_items: int
    all_required_metric: RatioMetricV3
    partial_metric: RatioMetricV3


class StageCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured_capacity: Optional[int] = None
    candidate_count: int
    scored_case_count: int
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    recall: Dict[str, Dict[int, RatioMetricV3]]
    mrr: Dict[str, RatioMetricV3]
    null_reason_counts: Dict[str, int] = Field(default_factory=dict)


class RetrievalCaseMetricsV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_version: Literal["3.0.0"] = "3.0.0"
    relevance_definition: Literal[
        "binary_unique_required_evidence_v1"
    ] = "binary_unique_required_evidence_v1"
    status: str
    applicable: bool
    skip_reason: Optional[str] = None
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    document_recall: Dict[int, RatioMetricV3]
    article_recall: Dict[int, RatioMetricV3]
    clause_recall: Dict[int, RatioMetricV3]
    mrr: Dict[str, RatioMetricV3]
    ndcg_at_10: RatioMetricV3
    exact_reference_hit: RatioMetricV3
    multi_hop: MultiHopCaseMetricsV3
    no_candidate: bool = False
    retrieval_technical_error: bool = False
    reranker_technical_error: bool = False
    stages: Dict[str, StageCaseMetricsV3]
    first_loss_by_evidence: Dict[str, str] = Field(default_factory=dict)



class StrictMetricModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationSchemaError(ValueError):
    status = "schema_error"


class AggregateMetric(StrictMetricModel):
    macro: Optional[float] = None
    micro: Optional[float] = None
    numerator: float = 0.0
    denominator: float = 0.0
    scored_cases: int = 0
    skipped_cases: int = 0
    skip_reasons: Dict[str, int] = Field(default_factory=dict)
    reason: Optional[str] = None


class CandidateDistribution(StrictMetricModel):
    count: int
    min: Optional[float] = None
    mean: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    max: Optional[float] = None


class StageAggregateMetrics(StrictMetricModel):
    configured_capacity: Optional[int] = None
    scored_case_count: int
    applicable_gold_counts: Dict[str, int]
    matched_gold_counts: Dict[str, int]
    recall: Dict[str, Dict[int, AggregateMetric]]
    mrr: Dict[str, AggregateMetric]
    candidates: CandidateDistribution
    first_loss_evidence_count: int = 0
    null_reason_counts: Dict[str, int] = Field(default_factory=dict)


class RetrievalAggregateMetrics(StrictMetricModel):
    metric_version: Literal["3.0.0"] = "3.0.0"
    total_cases: int
    scored_cases: int
    skipped_cases: int
    coverage: AggregateMetric
    skip_reason_counts: Dict[str, int]
    document_recall: Dict[int, AggregateMetric]
    article_recall: Dict[int, AggregateMetric]
    clause_recall: Dict[int, AggregateMetric]
    mrr: Dict[str, AggregateMetric]
    ndcg_at_10: AggregateMetric
    exact_reference_hit: AggregateMetric
    multi_hop_all_required: AggregateMetric
    multi_hop_partial: AggregateMetric
    no_candidate_rate: AggregateMetric
    retrieval_technical_error_rate: AggregateMetric
    reranker_technical_error_rate: AggregateMetric
    stages: Dict[str, StageAggregateMetrics]


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
    technical_errors: Dict[str, str] = Field(default_factory=dict)


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
    status: str = "ok"
    technical_errors: Dict[str, str] = Field(default_factory=dict)


class EvaluationRunManifest(BaseModel):
    run_id: str
    utc_timestamp: str
    git_sha: str
    git_dirty: bool = False
    git_tracked_dirty: bool = False
    git_staged_dirty: bool = False
    git_untracked_dirty: bool = False
    git_diff_sha256: Optional[str] = None
    git_diff_status: str = "clean"
    git_diff_reason: Optional[str] = None
    source_state_sha256: Optional[str] = None
    provenance_status: str = "ok"
    provenance_error: Optional[str] = None
    repository_root: str = ""
    dataset_revision: str
    dataset_sha256: str
    evaluation_dataset_sha256: str = ""
    gold_label_sidecar_sha256: Optional[str] = None
    gold_policy: str = "all-required-verified"
    selected_case_count: int = 0
    selected_case_ids: List[str] = Field(default_factory=list)
    selected_case_ids_sha256: Optional[str] = None
    configuration_fingerprint: str
    command: str
    eval_mode: str  # "retrieval-only" | "answer"
    judge_mode: str  # "none" | "ragas"
    guardrail_mode: str  # "off" | "shadow" | "enforce"
    rewrite_mode: str  # "off" | "on"
    reranker_provider: str  # "current" | "pinecone-bge" | "qdrant-colbert" | "pinecone-only" | "qdrant-only"
    profile_name: str = "custom"
    configuration: Dict[str, Any] = Field(default_factory=dict)
    configured_provider_models: Dict[str, Any] = Field(default_factory=dict)
    code_metric_version: str = "3.0.0"
