import hashlib
from typing import Dict, List, Optional

from app.ingestion.schemas import ExtractedMetadata, HierarchicalChunk, LegalASTNode


class HierarchicalChunker:
    """
    Builds deterministic chunks from AST-owned node text.

    `text` is owned source text only. `context_text` may add hierarchy/citation
    context for retrieval, but it is not used as a reconstruction proof.
    """

    def chunk_ast(
        self,
        root: LegalASTNode,
        document_id: str,
        doc_title: str,
        metadata: ExtractedMetadata,
        document_hash: str = "",
        body_hash: str = "",
        audit_id: str = "",
        pipeline_version: str = "",
        template_id: str = "unknown",
    ) -> List[HierarchicalChunk]:
        chunks: List[HierarchicalChunk] = []
        official_num = metadata.official_number.value or "UNKNOWN"
        doc_prefix = f"Document: {doc_title} | Number: {official_num}"
        context: Dict[str, Optional[str]] = {
            "chapter": None,
            "section": None,
            "article": None,
            "clause": None,
            "point": None,
        }

        self._traverse_and_chunk(
            node=root,
            document_id=document_id,
            doc_prefix=doc_prefix,
            context=context,
            parent_chunk_id=None,
            chunks=chunks,
            document_hash=document_hash,
            body_hash=body_hash,
            audit_id=audit_id,
            pipeline_version=pipeline_version,
            template_id=template_id,
        )
        return chunks

    def _traverse_and_chunk(
        self,
        node: LegalASTNode,
        document_id: str,
        doc_prefix: str,
        context: Dict[str, Optional[str]],
        parent_chunk_id: Optional[str],
        chunks: List[HierarchicalChunk],
        document_hash: str,
        body_hash: str,
        audit_id: str,
        pipeline_version: str,
        template_id: str,
    ):
        current_ctx = dict(context)
        self._update_context(node, current_ctx)

        current_chunk_id = parent_chunk_id
        if node.node_type != "document" and node.normalized_text.strip() and node.source_block_ids:
            chunk_id = self._chunk_id(document_id, node)
            citation_str = self._build_citation_header(doc_prefix, current_ctx)
            text = node.normalized_text.strip()
            context_text = f"[{citation_str}]\n{text}" if citation_str else text

            chunk = HierarchicalChunk(
                chunk_id=chunk_id,
                parent_chunk_id=parent_chunk_id,
                document_id=document_id,
                node_id=node.node_id,
                node_type=node.node_type,
                text=text,
                context_text=context_text,
                citation={
                    "doc_title": doc_prefix,
                    "chapter": current_ctx.get("chapter"),
                    "section": current_ctx.get("section"),
                    "article": current_ctx.get("article"),
                    "clause": current_ctx.get("clause"),
                    "point": current_ctx.get("point"),
                },
                source_block_ids=list(node.source_block_ids),
                document_hash=document_hash,
                body_hash=body_hash,
                audit_id=audit_id,
                pipeline_version=pipeline_version,
                template_id=template_id,
            )
            chunks.append(chunk)
            current_chunk_id = chunk_id

        for child in node.children:
            self._traverse_and_chunk(
                node=child,
                document_id=document_id,
                doc_prefix=doc_prefix,
                context=current_ctx,
                parent_chunk_id=current_chunk_id,
                chunks=chunks,
                document_hash=document_hash,
                body_hash=body_hash,
                audit_id=audit_id,
                pipeline_version=pipeline_version,
                template_id=template_id,
            )

    def _update_context(self, node: LegalASTNode, ctx: Dict[str, Optional[str]]):
        if node.node_type == "chapter":
            ctx["chapter"] = self._label("Chuong", node)
            ctx["section"] = None
            ctx["article"] = None
            ctx["clause"] = None
            ctx["point"] = None
        elif node.node_type == "section":
            ctx["section"] = self._label("Muc", node)
            ctx["article"] = None
            ctx["clause"] = None
            ctx["point"] = None
        elif node.node_type == "article":
            ctx["article"] = self._label("Dieu", node)
            ctx["clause"] = None
            ctx["point"] = None
        elif node.node_type == "clause":
            ctx["clause"] = self._label("Khoan", node)
            ctx["point"] = None
        elif node.node_type == "point":
            ctx["point"] = self._label("Diem", node)
        elif node.node_type == "appendix":
            ctx["chapter"] = self._label("Phu luc", node)
            ctx["section"] = None
            ctx["article"] = None
            ctx["clause"] = None
            ctx["point"] = None

    def _label(self, prefix: str, node: LegalASTNode) -> str:
        label = f"{prefix} {node.number or ''}".strip()
        if node.title:
            label += f": {node.title}"
        return label

    def _build_citation_header(self, doc_prefix: str, ctx: Dict[str, Optional[str]]) -> str:
        parts = [doc_prefix]
        for key in ["chapter", "section", "article", "clause", "point"]:
            if ctx.get(key):
                parts.append(ctx[key] or "")
        return " | ".join(parts)

    def _chunk_id(self, document_id: str, node: LegalASTNode) -> str:
        basis = "|".join([document_id, node.node_id, ",".join(node.source_block_ids)])
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
        return f"chunk_{node.node_type}_{digest}"
