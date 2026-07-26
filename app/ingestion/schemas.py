from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union

class LegalDocumentSchema(BaseModel):
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
    attributes: Dict[str, Any] = Field(default_factory=dict)
    relations: Dict[str, List[str]] = Field(default_factory=dict)

class ExtractedMetadataField(BaseModel):
    value: Optional[str] = "UNKNOWN"
    source: str = "unknown"
    method: str = "none"
    confidence: float = 0.0
    reason: Optional[str] = None

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

class HierarchicalChunk(BaseModel):
    chunk_id: str
    parent_chunk_id: Optional[str] = None
    document_id: str
    node_id: str
    node_type: str
    text: str
    context_text: str
    citation: Dict[str, Optional[str]] = Field(default_factory=dict)

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

