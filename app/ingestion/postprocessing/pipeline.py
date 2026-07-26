import json
import sys
import logfire
from typing import Dict, Any, Union

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from app.ingestion.schemas import LegalDocumentSchema, ProcessedLegalDocument
from app.ingestion.postprocessing.metadata_resolver import MetadataResolver
from app.ingestion.postprocessing.text_normalizer import TextNormalizer
from app.ingestion.postprocessing.structure_parser import StructureParser
from app.ingestion.postprocessing.validator import StructureValidator
from app.ingestion.postprocessing.confidence_scorer import ConfidenceScorer
from app.ingestion.postprocessing.chunker import HierarchicalChunker

class LegalPreprocessingPipeline:
    """
    Master Post-Processing & Preprocessing Pipeline for Vietnamese Legal Documents.
    Executes Phases 2 through 9 synchronously with zero hallucination and strict audit logs.
    """

    def __init__(self):
        self.metadata_resolver = MetadataResolver()
        self.normalizer = TextNormalizer()
        self.parser = StructureParser()
        self.validator = StructureValidator()
        self.confidence_scorer = ConfidenceScorer()
        self.chunker = HierarchicalChunker()

    def process(self, doc_input: Union[LegalDocumentSchema, Dict[str, Any]]) -> ProcessedLegalDocument:
        if isinstance(doc_input, dict):
            doc = LegalDocumentSchema(**doc_input)
        else:
            doc = doc_input

        # Phase 2: Metadata Resolution
        extracted_meta = self.metadata_resolver.resolve(doc)

        # Phase 3: Text Normalization & Block Building
        text_blocks = self.normalizer.build_text_blocks(
            full_text=doc.full_text,
            html_text=doc.html_text,
            source=doc.source
        )

        # Phase 4: Structure Parsing & AST State Machine
        ast_root = self.parser.parse(blocks=text_blocks, doc_title=doc.title)

        # Phase 5: Validation & Integrity Audit
        validation_result = self.validator.validate(root=ast_root, original_full_text=doc.full_text)

        # Phase 6: Confidence Scoring
        self.confidence_scorer.score_ast(ast_root)

        # Phase 8: Hierarchical Parent-Child Chunking
        chunks = self.chunker.chunk_ast(
            root=ast_root,
            document_id=doc.source_id or "doc_unk",
            doc_title=doc.title,
            metadata=extracted_meta
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
            chunks=chunks
        )

        # Phase 9: Print Audit Report
        self.print_audit_report(processed_doc, len(text_blocks))

        return processed_doc

    def print_audit_report(self, doc: ProcessedLegalDocument, block_count: int):
        v = doc.validation
        meta = doc.metadata

        # Count structural nodes
        node_counts = {"chapters": 0, "sections": 0, "articles": 0, "clauses": 0, "points": 0}
        self._count_nodes(doc.legal_structure, node_counts)

        audit_str = f"""
=== LEGAL PREPROCESSING AUDIT ===
source: {doc.source}
source_id: {doc.source_id}
url: {doc.url}

raw_full_text_chars: {v.char_count_raw}
normalized_text_chars: {v.char_count_ast}
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
duplicated_text: {len(v.duplicate_numberings)}
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
