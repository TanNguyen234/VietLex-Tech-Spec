import re
import logfire
from typing import List, Dict, Optional

@logfire.instrument("Phân tách văn bản luật với Context Enrichment")
def parse_legal_document_with_context(file_content: str, metadata: Optional[Dict] = None) -> List[Dict]:
    from app.ingestion.schemas import LegalDocumentSchema
    from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline

    meta = metadata or {}
    doc = LegalDocumentSchema(
        source_id=str(meta.get("source_id", "doc_unk")),
        source=str(meta.get("source", "unknown")),
        url=str(meta.get("url", "")),
        title=str(meta.get("title", "Văn bản Luật")),
        official_number=str(meta.get("official_number", "")),
        full_text=file_content,
        html_text=str(meta.get("html_text", ""))
    )

    pipeline = LegalPreprocessingPipeline()
    processed_doc = pipeline.process(doc)

    result_chunks = []
    for c in processed_doc.chunks:
        result_chunks.append({
            "chunk_id": c.chunk_id,
            "parent_chunk_id": c.parent_chunk_id,
            "chapter": c.citation.get("chapter") or "Chương chung",
            "section": c.citation.get("section") or "Mục chung",
            "article": c.citation.get("article") or "Điều chung",
            "clause": c.citation.get("clause"),
            "content": c.context_text,
            "raw_article_body": c.text,
            "header_prefix": c.citation.get("doc_title", "")
        })

    logfire.info("Phân tách hoàn tất với Pipeline Postprocessing. Số lượng chunks: {count}", count=len(result_chunks))
    return result_chunks

@logfire.instrument("Phân tách văn bản luật")
def parse_legal_document(file_content: str) -> List[Dict]:
    return parse_legal_document_with_context(file_content, metadata=None)

