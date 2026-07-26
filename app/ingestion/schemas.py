from enum import Enum
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from typing import Dict, List, Optional, Any


class ProcessingDisposition(str, Enum):
    PASS = "PASS"
    PASS_WITH_UNKNOWN_METADATA = "PASS_WITH_UNKNOWN_METADATA"
    AMBIGUOUS = "AMBIGUOUS"
    FAIL = "FAIL"


class EvidenceNode(BaseModel):
    name: str
    source: str
    passed: bool
    detail: str = ""
    value: Optional[str] = None
    value_hash: Optional[str] = None


class EvidenceGraph(BaseModel):
    candidate_id: str
    source: str
    body_hash: str = ""
    normalized_char_count: int = 0
    evidence: List[EvidenceNode] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)


class ConfidenceExplanation(BaseModel):
    decision: str = "Fail"
    winner: str = "none"
    evidence_passed: List[str] = Field(default_factory=list)
    evidence_failed: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    reason: str = ""
    score: float = 0.0


class TemplateRegistryEntry(BaseModel):
    source: str = "unknown"
    template_id: str = "unknown"
    extractor: str = "generic"
    owner: str = "unknown"
    supported_version: str = "0"
    status: str = "UNKNOWN"
    fingerprints: List[str] = Field(default_factory=list)
    notes: str = ""


class BodyCandidate(BaseModel):
    candidate_id: str
    source: str
    text: str
    blocks: List["TextBlock"] = Field(default_factory=list)
    evidence_graph: EvidenceGraph


class BodyResolution(BaseModel):
    disposition: ProcessingDisposition
    selected_candidate: Optional[BodyCandidate] = None
    candidates: List[BodyCandidate] = Field(default_factory=list)
    confidence: ConfidenceExplanation = Field(default_factory=ConfidenceExplanation)
    template: TemplateRegistryEntry = Field(default_factory=TemplateRegistryEntry)
    document_hash: str = ""
    body_hash: str = ""
    audit_id: str = ""


class IntegrityReport(BaseModel):
    audit_id: str = ""
    pipeline_version: str = ""
    disposition: ProcessingDisposition = ProcessingDisposition.FAIL
    document_hash: str = ""
    body_hash: str = ""
    template_id: str = "unknown"
    candidate_decision: str = "Fail"
    confidence: ConfidenceExplanation = Field(default_factory=ConfidenceExplanation)
    evidence_graph: Optional[EvidenceGraph] = None
    validation_status: str = "FAIL"
    index_outcome: str = "not_attempted"
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

class LegalDocumentSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    source_id: str
    source: str
    url: str
    title: str
    document_type: Optional[str] = ""
    official_number: Optional[str] = ""
    issued_date: Optional[str] = ""
    effective_date: Optional[str] = ""
    enforced_date: Optional[str] = ""
    expiry_date: Optional[str] = ""
    issuing_body: Optional[str] = ""
    signer: Optional[str] = ""
    status: Optional[str] = ""
    full_text: str
    html_text: Optional[str] = ""
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("attributes", "attribute"),
    )
    relations: Dict[str, List[str]] = Field(default_factory=dict)
    raw_schema: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("raw_schema", "schema"),
    )

class ExtractedMetadataField(BaseModel):
    value: Optional[str] = "UNKNOWN"
    source: str = "unknown"
    method: str = "none"
    confidence: float = 0.0
    reason: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    conflicts: List[str] = Field(default_factory=list)

class ExtractedMetadata(BaseModel):
    document_type: ExtractedMetadataField
    official_number: ExtractedMetadataField
    issued_date: ExtractedMetadataField
    effective_date: ExtractedMetadataField
    enforced_date: ExtractedMetadataField
    expiry_date: ExtractedMetadataField
    issuing_body: ExtractedMetadataField
    signer: ExtractedMetadataField
    status: ExtractedMetadataField

class TextBlock(BaseModel):
    block_id: str
    order: int
    raw_text: str
    normalized_text: str
    source_tag: Optional[str] = None
    dom_path: Optional[str] = None
    source: Optional[str] = None

class LegalASTNode(BaseModel):
    node_id: str
    node_type: str  # document, preamble, chapter, section, article, clause, point, subpoint, appendix, signature
    number: Optional[str] = None
    title: Optional[str] = None
    raw_text: str = ""
    normalized_text: str = ""
    parent_id: Optional[str] = None
    children: List['LegalASTNode'] = Field(default_factory=list)
    source_block_ids: List[str] = Field(default_factory=list)
    unresolved_block_ids: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    detection_method: str = "deterministic"

class ValidationAuditResult(BaseModel):
    status: str = "PASS" # PASS, WARNING, FAIL, AMBIGUOUS
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    missing_sequences: List[str] = Field(default_factory=list)
    duplicate_numberings: List[str] = Field(default_factory=list)
    unresolved_blocks: List[str] = Field(default_factory=list)
    char_count_raw: int = 0
    char_count_ast: int = 0
    text_loss_percentage: float = 0.0
    raw_hash: Optional[str] = None
    ast_hash: Optional[str] = None
    block_coverage: Dict[str, int] = Field(default_factory=dict)

class HierarchicalChunk(BaseModel):
    chunk_id: str
    parent_chunk_id: Optional[str] = None
    document_id: str
    node_id: str
    node_type: str
    text: str
    context_text: str
    citation: Dict[str, Optional[str]] = Field(default_factory=dict)
    source_block_ids: List[str] = Field(default_factory=list)
    document_hash: Optional[str] = None
    body_hash: Optional[str] = None
    audit_id: Optional[str] = None
    pipeline_version: Optional[str] = None
    template_id: Optional[str] = None

class ProcessedLegalDocument(BaseModel):
    source_id: str
    source: str
    url: str
    title: str
    full_text: str
    html_text: Optional[str] = ""
    metadata: ExtractedMetadata
    legal_structure: LegalASTNode
    validation: ValidationAuditResult
    chunks: List[HierarchicalChunk] = Field(default_factory=list)
    disposition: ProcessingDisposition = ProcessingDisposition.FAIL
    audit_id: str = ""
    pipeline_version: str = ""
    document_hash: str = ""
    body_hash: str = ""
    template_id: str = "unknown"
    body_source: str = "none"
    candidate_decision: str = "Fail"
    confidence_explanation: ConfidenceExplanation = Field(default_factory=ConfidenceExplanation)
    evidence_graph: Optional[EvidenceGraph] = None
    integrity_report: IntegrityReport = Field(default_factory=IntegrityReport)


BodyCandidate.model_rebuild()
LegalASTNode.model_rebuild()
