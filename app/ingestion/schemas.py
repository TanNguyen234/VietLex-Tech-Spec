from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

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
