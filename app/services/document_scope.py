"""Deterministic retrieval inside one explicitly selected public document."""
from __future__ import annotations

import re

from app.config import get_settings
from app.ingestion.legal_text import chunk_document
from app.ingestion.pinecone_store import fast_terms
from app.services.retrieval import RetrievalOutcome, lexical_prefilter, select_ranked_evidence


def document_evidence(query: str, document) -> RetrievalOutcome:
    settings = get_settings()
    chunks = chunk_document(document.metadata, document.content,
                            max_tokens=settings.QUERY_CHUNK_MAX_TOKENS,
                            overlap_tokens=settings.QUERY_CHUNK_OVERLAP_TOKENS)
    articles = {value.casefold() for value in re.findall(r"\bđiều\s+(\d+[a-z]?)\b", query, re.I)}
    clauses = set(re.findall(r"\bkhoản\s+(\d+)\b", query, re.I))
    terms = set(fast_terms(query))
    candidates = [chunk for chunk in chunks
                  if (not articles or (chunk.article or "").casefold().removeprefix("điều ") in articles)
                  and (not clauses or (chunk.clause or "").casefold().removeprefix("khoản ") in clauses)
                  and (articles or clauses or terms.intersection(fast_terms(chunk.text)))]
    ranked = lexical_prefilter(query, candidates, limit=settings.FINAL_EVIDENCE_LIMIT,
                               tokenize=fast_terms)
    evidence = select_ranked_evidence(
        [(1.0, chunk) for chunk in ranked], max_chunks=settings.FINAL_EVIDENCE_LIMIT,
        max_tokens=settings.LLM_CONTEXT_MAX_TOKENS,
        per_document_limit=settings.FINAL_EVIDENCE_LIMIT, min_score=0.0,
    )
    return RetrievalOutcome(evidence=evidence, latency={}, diagnostics={
        "retrieval_backend": "document_lexical_v1", "document_id": document.metadata.document_id,
        "scope": "document", "candidate_count": len(candidates),
        "scope_expanded": False,
    })
