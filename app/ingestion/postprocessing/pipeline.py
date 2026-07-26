import sys
from typing import Any, Dict, Union

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ingestion.schemas import (
    IntegrityReport,
    LegalASTNode,
    LegalDocumentSchema,
    ProcessedLegalDocument,
    ProcessingDisposition,
    ValidationAuditResult,
)
from app.ingestion.postprocessing.body_resolver import BodyResolver
from app.ingestion.postprocessing.chunker import HierarchicalChunker
from app.ingestion.postprocessing.confidence_scorer import ConfidenceScorer
from app.ingestion.postprocessing.metadata_resolver import MetadataResolver
from app.ingestion.postprocessing.structure_parser import StructureParser
from app.ingestion.postprocessing.template_registry import TemplateRegistry
from app.ingestion.postprocessing.text_normalizer import TextNormalizer
from app.ingestion.postprocessing.validator import StructureValidator


PIPELINE_VERSION = "integrity-first-v2"
PASSING_DISPOSITIONS = {
    ProcessingDisposition.PASS,
    ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA,
}


class LegalPreprocessingPipeline:
    """
    Integrity-first preprocessing pipeline for Vietnamese legal documents.

    The public facade remains compatible, but internal processing now resolves
    the canonical body through evidence before parsing or chunking.
    """

    def __init__(self):
        self.metadata_resolver = MetadataResolver()
        self.normalizer = TextNormalizer()
        self.template_registry = TemplateRegistry()
        self.body_resolver = BodyResolver(self.normalizer)
        self.parser = StructureParser()
        self.validator = StructureValidator()
        self.confidence_scorer = ConfidenceScorer()
        self.chunker = HierarchicalChunker()

    def process(self, doc_input: Union[LegalDocumentSchema, Dict[str, Any]]) -> ProcessedLegalDocument:
        doc = LegalDocumentSchema(**doc_input) if isinstance(doc_input, dict) else doc_input
        template = self.template_registry.resolve(doc)
        body_resolution = self.body_resolver.resolve(doc, template)

        if body_resolution.selected_candidate is None:
            processed = self._blocked_document(doc, body_resolution)
            self.print_audit_report(processed, 0)
            return processed

        selected = body_resolution.selected_candidate
        extracted_meta = self.metadata_resolver.resolve(doc, body_text=selected.text)

        ast_root = self.parser.parse(
            blocks=selected.blocks,
            doc_title=doc.title,
            document_id=doc.source_id or body_resolution.document_hash[:12],
        )

        validation_result = self.validator.validate(
            root=ast_root,
            original_full_text=selected.text,
            blocks=selected.blocks,
            body_hash=body_resolution.body_hash,
        )

        disposition = self._disposition(validation_result, extracted_meta)
        if template.status.upper() == "BROKEN":
            validation_result.errors.append(f"TEMPLATE_BROKEN: {template.template_id}")
            validation_result.status = "FAIL"
            disposition = ProcessingDisposition.FAIL
        elif template.status.upper() == "UNKNOWN" and doc.html_text and selected.source == "html":
            validation_result.errors.append(f"UNKNOWN_HTML_TEMPLATE: {template.template_id}")
            validation_result.status = "FAIL"
            disposition = ProcessingDisposition.FAIL

        self.confidence_scorer.score_ast(ast_root)

        chunks = []
        if disposition in PASSING_DISPOSITIONS:
            chunks = self.chunker.chunk_ast(
                root=ast_root,
                document_id=doc.source_id or body_resolution.document_hash[:12],
                doc_title=doc.title,
                metadata=extracted_meta,
                document_hash=body_resolution.document_hash,
                body_hash=body_resolution.body_hash,
                audit_id=body_resolution.audit_id,
                pipeline_version=PIPELINE_VERSION,
                template_id=template.template_id,
            )

        processed_doc = ProcessedLegalDocument(
            source_id=doc.source_id,
            source=doc.source,
            url=doc.url,
            title=doc.title,
            full_text=doc.full_text,
            html_text=doc.html_text,
            metadata=extracted_meta,
            legal_structure=ast_root,
            validation=validation_result,
            chunks=chunks,
            disposition=disposition,
            audit_id=body_resolution.audit_id,
            pipeline_version=PIPELINE_VERSION,
            document_hash=body_resolution.document_hash,
            body_hash=body_resolution.body_hash,
            template_id=template.template_id,
            body_source=selected.source,
            candidate_decision=body_resolution.confidence.decision,
            confidence_explanation=body_resolution.confidence,
            evidence_graph=selected.evidence_graph,
        )
        processed_doc.integrity_report = self._integrity_report(processed_doc, index_outcome="not_attempted")

        self.print_audit_report(processed_doc, len(selected.blocks))
        return processed_doc

    def _blocked_document(self, doc: LegalDocumentSchema, body_resolution) -> ProcessedLegalDocument:
        validation = ValidationAuditResult(
            status=body_resolution.disposition.value,
            errors=[body_resolution.confidence.reason] if body_resolution.confidence.reason else [],
        )
        root = LegalASTNode(
            node_id=f"doc_{doc.source_id or body_resolution.document_hash[:12] or 'doc_unk'}",
            node_type="document",
            title=doc.title,
        )
        metadata = self.metadata_resolver.resolve(doc)
        processed = ProcessedLegalDocument(
            source_id=doc.source_id,
            source=doc.source,
            url=doc.url,
            title=doc.title,
            full_text=doc.full_text,
            html_text=doc.html_text,
            metadata=metadata,
            legal_structure=root,
            validation=validation,
            chunks=[],
            disposition=body_resolution.disposition,
            audit_id=body_resolution.audit_id,
            pipeline_version=PIPELINE_VERSION,
            document_hash=body_resolution.document_hash,
            body_hash=body_resolution.body_hash,
            template_id=body_resolution.template.template_id,
            body_source="none",
            candidate_decision=body_resolution.confidence.decision,
            confidence_explanation=body_resolution.confidence,
            evidence_graph=None,
        )
        processed.integrity_report = self._integrity_report(processed, index_outcome="not_attempted")
        return processed

    def _disposition(self, validation: ValidationAuditResult, metadata) -> ProcessingDisposition:
        if validation.status == "FAIL":
            return ProcessingDisposition.FAIL

        metadata_values = [
            metadata.document_type.value,
            metadata.official_number.value,
            metadata.issued_date.value,
            metadata.effective_date.value,
            metadata.enforced_date.value,
            metadata.expiry_date.value,
            metadata.issuing_body.value,
            metadata.signer.value,
            metadata.status.value,
        ]
        if any(not value or value == "UNKNOWN" for value in metadata_values):
            return ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA
        return ProcessingDisposition.PASS

    def _integrity_report(self, doc: ProcessedLegalDocument, index_outcome: str) -> IntegrityReport:
        return IntegrityReport(
            audit_id=doc.audit_id,
            pipeline_version=doc.pipeline_version,
            disposition=doc.disposition,
            document_hash=doc.document_hash,
            body_hash=doc.body_hash,
            template_id=doc.template_id,
            candidate_decision=doc.candidate_decision,
            confidence=doc.confidence_explanation,
            evidence_graph=doc.evidence_graph,
            validation_status=doc.validation.status,
            index_outcome=index_outcome,
            warnings=doc.validation.warnings,
            errors=doc.validation.errors,
        )

    def print_audit_report(self, doc: ProcessedLegalDocument, block_count: int):
        v = doc.validation
        meta = doc.metadata
        c = doc.confidence_explanation

        node_counts = {"chapters": 0, "sections": 0, "articles": 0, "clauses": 0, "points": 0}
        self._count_nodes(doc.legal_structure, node_counts)

        passed = ", ".join(c.evidence_passed[:8])
        failed = ", ".join(c.evidence_failed[:8])
        conflicts = ", ".join(c.conflicts[:3])

        audit_str = f"""
=== LEGAL PREPROCESSING AUDIT ===
pipeline_version: {doc.pipeline_version}
audit_id: {doc.audit_id}
source: {doc.source}
source_id: {doc.source_id}
url: {doc.url}
template_id: {doc.template_id}

decision: {c.decision}
winner: {c.winner}
disposition: {doc.disposition.value}
reason: {c.reason}
evidence_passed: {passed}
evidence_failed: {failed}
conflicts: {conflicts}

document_hash: {doc.document_hash}
body_hash: {doc.body_hash}
body_source: {doc.body_source}

raw_body_chars: {v.char_count_raw}
ast_owned_chars: {v.char_count_ast}
text_loss_percentage: {v.text_loss_percentage}%
text_blocks: {block_count}

chapters: {node_counts['chapters']}
sections: {node_counts['sections']}
articles: {node_counts['articles']}
clauses: {node_counts['clauses']}
points: {node_counts['points']}

metadata_extracted:
  - document_type: {meta.document_type.value} (conf: {meta.document_type.confidence})
  - official_number: {meta.official_number.value} (conf: {meta.official_number.confidence})
  - issued_date: {meta.issued_date.value} (conf: {meta.issued_date.confidence})
  - effective_date: {meta.effective_date.value} (conf: {meta.effective_date.confidence})
  - issuing_body: {meta.issuing_body.value} (conf: {meta.issuing_body.confidence})
  - signer: {meta.signer.value} (conf: {meta.signer.confidence})
  - status: {meta.status.value} (conf: {meta.status.confidence})

missing_sequences: {len(v.missing_sequences)} ({', '.join(v.missing_sequences[:3])})
duplicated_blocks: {len([k for k, val in v.block_coverage.items() if val > 1])}
unresolved_blocks: {len(v.unresolved_blocks)}
validation_status: {v.status}
warnings: {len(v.warnings)}
errors: {len(v.errors)}
=================================
"""
        print(audit_str)

    def _count_nodes(self, node, counts: Dict[str, int]):
        if node.node_type == "chapter":
            counts["chapters"] += 1
        elif node.node_type == "section":
            counts["sections"] += 1
        elif node.node_type == "article":
            counts["articles"] += 1
        elif node.node_type == "clause":
            counts["clauses"] += 1
        elif node.node_type == "point":
            counts["points"] += 1

        for child in node.children:
            self._count_nodes(child, counts)
