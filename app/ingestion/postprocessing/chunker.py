import uuid
from typing import List, Dict, Optional
from app.ingestion.schemas import LegalASTNode, HierarchicalChunk, ExtractedMetadata

class HierarchicalChunker:
    """
    Hierarchical Parent-Child Chunker (Phase 8).
    Creates Parent (Article) and Child (Clause/Point) chunks enriched with full citation headers.
    """

    def chunk_ast(
        self,
        root: LegalASTNode,
        document_id: str,
        doc_title: str,
        metadata: ExtractedMetadata
    ) -> List[HierarchicalChunk]:
        chunks: List[HierarchicalChunk] = []

        official_num = metadata.official_number.value or "Không có số hiệu"
        doc_prefix = f"Văn bản: {doc_title} | Số hiệu: {official_num}"

        # Traversal context state
        context = {
            "chapter": None,
            "section": None,
            "article": None,
            "clause": None
        }

        self._traverse_and_chunk(
            node=root,
            document_id=document_id,
            doc_prefix=doc_prefix,
            context=context,
            parent_chunk_id=None,
            chunks=chunks
        )

        return chunks

    def _traverse_and_chunk(
        self,
        node: LegalASTNode,
        document_id: str,
        doc_prefix: str,
        context: Dict[str, Optional[str]],
        parent_chunk_id: Optional[str],
        chunks: List[HierarchicalChunk]
    ):
        current_ctx = dict(context)

        if node.node_type == "chapter":
            current_ctx["chapter"] = f"Chương {node.number or ''}".strip()
            if node.title:
                current_ctx["chapter"] += f": {node.title}"
        elif node.node_type == "section":
            current_ctx["section"] = f"Mục {node.number or ''}".strip()
            if node.title:
                current_ctx["section"] += f": {node.title}"
        elif node.node_type == "article":
            art_str = f"Điều {node.number or ''}".strip()
            if node.title:
                art_str += f". {node.title}"
            current_ctx["article"] = art_str

            # Create Parent Chunk for Article
            art_chunk_id = f"chunk_art_{uuid.uuid4().hex[:8]}"
            citation_str = self._build_citation_header(doc_prefix, current_ctx)

            full_art_body = self._collect_node_text(node)
            context_text = f"[{citation_str}]\n{full_art_body}"

            art_chunk = HierarchicalChunk(
                chunk_id=art_chunk_id,
                parent_chunk_id=None,
                document_id=document_id,
                node_id=node.node_id,
                node_type="article",
                text=full_art_body,
                context_text=context_text,
                citation={
                    "doc_title": doc_prefix,
                    "chapter": current_ctx.get("chapter"),
                    "section": current_ctx.get("section"),
                    "article": current_ctx.get("article"),
                    "clause": None,
                    "point": None
                }
            )
            chunks.append(art_chunk)

            # Traverse child clauses or points under this Article
            for child in node.children:
                self._traverse_and_chunk(
                    node=child,
                    document_id=document_id,
                    doc_prefix=doc_prefix,
                    context=current_ctx,
                    parent_chunk_id=art_chunk_id,
                    chunks=chunks
                )
            return

        elif node.node_type == "clause":
            cls_str = f"Khoản {node.number or ''}".strip()
            current_ctx["clause"] = cls_str

            cls_chunk_id = f"chunk_cls_{uuid.uuid4().hex[:8]}"
            citation_str = self._build_citation_header(doc_prefix, current_ctx)
            cls_body = self._collect_node_text(node)
            context_text = f"[{citation_str}]\n{cls_body}"

            cls_chunk = HierarchicalChunk(
                chunk_id=cls_chunk_id,
                parent_chunk_id=parent_chunk_id,
                document_id=document_id,
                node_id=node.node_id,
                node_type="clause",
                text=cls_body,
                context_text=context_text,
                citation={
                    "doc_title": doc_prefix,
                    "chapter": current_ctx.get("chapter"),
                    "section": current_ctx.get("section"),
                    "article": current_ctx.get("article"),
                    "clause": cls_str,
                    "point": None
                }
            )
            chunks.append(cls_chunk)

            for child in node.children:
                self._traverse_and_chunk(
                    node=child,
                    document_id=document_id,
                    doc_prefix=doc_prefix,
                    context=current_ctx,
                    parent_chunk_id=cls_chunk_id,
                    chunks=chunks
                )
            return

        # Fallback for children
        for child in node.children:
            self._traverse_and_chunk(
                node=child,
                document_id=document_id,
                doc_prefix=doc_prefix,
                context=current_ctx,
                parent_chunk_id=parent_chunk_id,
                chunks=chunks
            )

    def _build_citation_header(self, doc_prefix: str, ctx: Dict[str, Optional[str]]) -> str:
        parts = [doc_prefix]
        if ctx.get("chapter"):
            parts.append(ctx["chapter"])
        if ctx.get("section"):
            parts.append(ctx["section"])
        if ctx.get("article"):
            parts.append(ctx["article"])
        if ctx.get("clause"):
            parts.append(ctx["clause"])
        return " | ".join(parts)

    def _collect_node_text(self, node: LegalASTNode) -> str:
        texts = []
        if node.normalized_text:
            texts.append(node.normalized_text)
        for child in node.children:
            c_text = self._collect_node_text(child)
            if c_text:
                texts.append(c_text)
        return "\n".join(texts)
