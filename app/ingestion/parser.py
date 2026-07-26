import logfire
from typing import Dict, List, Optional

from app.ingestion.schemas import LegalDocumentSchema, ProcessingDisposition


PASSING_DISPOSITIONS = {
    ProcessingDisposition.PASS,
    ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA,
}


@logfire.instrument("Parse legal document with integrity-first context enrichment")
def parse_legal_document_with_context(file_content: str, metadata: Optional[Dict] = None) -> List[Dict]:
    from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline

    meta = metadata or {}
    attributes = meta.get("attributes") or meta.get("attribute") or {}
    raw_schema = meta.get("raw_schema") or meta.get("schema") or {}

    doc = LegalDocumentSchema(
        source_id=str(meta.get("source_id", "doc_unk")),
        source=str(meta.get("source", "unknown")),
        url=str(meta.get("url", "")),
        title=str(meta.get("title", "Van ban Luat")),
        document_type=str(meta.get("document_type", "")),
        official_number=str(meta.get("official_number", "")),
        issued_date=str(meta.get("issued_date", "")),
        effective_date=str(meta.get("effective_date", "")),
        enforced_date=str(meta.get("enforced_date", "")),
        expiry_date=str(meta.get("expiry_date", "")),
        issuing_body=str(meta.get("issuing_body", "")),
        signer=str(meta.get("signer", "")),
        status=str(meta.get("status", "")),
        full_text=file_content,
        html_text=str(meta.get("html_text", "")),
        attributes=attributes,
        relations=meta.get("relations", {}) or {},
        raw_schema=raw_schema,
    )

    pipeline = LegalPreprocessingPipeline()
    processed_doc = pipeline.process(doc)

    if processed_doc.disposition not in PASSING_DISPOSITIONS:
        logfire.warning(
            "Legal document blocked by integrity gate. source_id={source_id}, disposition={disposition}, audit_id={audit_id}",
            source_id=processed_doc.source_id,
            disposition=processed_doc.disposition.value,
            audit_id=processed_doc.audit_id,
        )
        return []

    result_chunks = []
    for chunk in processed_doc.chunks:
        result_chunks.append({
            "chunk_id": chunk.chunk_id,
            "parent_chunk_id": chunk.parent_chunk_id,
            "chapter": chunk.citation.get("chapter") or "Chuong chung",
            "section": chunk.citation.get("section") or "Muc chung",
            "article": chunk.citation.get("article") or "Dieu chung",
            "clause": chunk.citation.get("clause"),
            "content": chunk.context_text,
            "raw_article_body": chunk.text,
            "header_prefix": chunk.citation.get("doc_title", ""),
            "node_id": chunk.node_id,
            "node_type": chunk.node_type,
            "source_block_ids": chunk.source_block_ids,
            "document_hash": chunk.document_hash,
            "body_hash": chunk.body_hash,
            "audit_id": chunk.audit_id,
            "pipeline_version": chunk.pipeline_version,
            "template_id": chunk.template_id,
            "disposition": processed_doc.disposition.value,
            "candidate_decision": processed_doc.candidate_decision,
            "body_source": processed_doc.body_source,
        })

    logfire.info(
        "Legal parsing completed. chunks={count}, source_id={source_id}, audit_id={audit_id}",
        count=len(result_chunks),
        source_id=processed_doc.source_id,
        audit_id=processed_doc.audit_id,
    )
    return result_chunks


@logfire.instrument("Parse legal document")
def parse_legal_document(file_content: str) -> List[Dict]:
    return parse_legal_document_with_context(file_content, metadata=None)
