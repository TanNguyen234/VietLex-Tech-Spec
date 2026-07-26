import uuid
from typing import Optional, List
from app.ingestion.schemas import LegalASTNode, TextBlock

class DeterministicStateMachine:
    """
    Deterministic State Machine for Legal Document Hierarchy.
    Ensures strict parent-child scope tracking and prevents context leakage across nodes.
    """

    def __init__(self, doc_title: str = "Legal Document"):
        self.root = LegalASTNode(
            node_id=f"doc_{uuid.uuid4().hex[:8]}",
            node_type="document",
            title=doc_title,
            children=[],
            confidence=1.0,
            detection_method="deterministic"
        )
        self.current_preamble: Optional[LegalASTNode] = None
        self.current_chapter: Optional[LegalASTNode] = None
        self.current_section: Optional[LegalASTNode] = None
        self.current_article: Optional[LegalASTNode] = None
        self.current_clause: Optional[LegalASTNode] = None
        self.current_point: Optional[LegalASTNode] = None
        self.current_subpoint: Optional[LegalASTNode] = None
        self.current_appendix: Optional[LegalASTNode] = None

    def add_chapter(self, number: str, title: str, block: TextBlock, confidence: float = 1.0) -> LegalASTNode:
        node = LegalASTNode(
            node_id=f"chap_{block.block_id}",
            node_type="chapter",
            number=number,
            title=title,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=self.root.node_id,
            source_block_ids=[block.block_id],
            confidence=confidence
        )
        self.root.children.append(node)
        self.current_chapter = node
        self.current_section = None
        self.current_article = None
        self.current_clause = None
        self.current_point = None
        self.current_subpoint = None
        return node

    def add_section(self, number: str, title: str, block: TextBlock, confidence: float = 1.0) -> LegalASTNode:
        parent = self.current_chapter or self.root
        node = LegalASTNode(
            node_id=f"sec_{block.block_id}",
            node_type="section",
            number=number,
            title=title,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=parent.node_id,
            source_block_ids=[block.block_id],
            confidence=confidence
        )
        parent.children.append(node)
        self.current_section = node
        self.current_article = None
        self.current_clause = None
        self.current_point = None
        self.current_subpoint = None
        return node

    def add_article(self, number: str, title: str, block: TextBlock, confidence: float = 1.0) -> LegalASTNode:
        parent = self.current_section or self.current_chapter or self.root
        node = LegalASTNode(
            node_id=f"art_{block.block_id}",
            node_type="article",
            number=number,
            title=title,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=parent.node_id,
            source_block_ids=[block.block_id],
            confidence=confidence
        )
        parent.children.append(node)
        self.current_article = node
        # Context Isolation: Reset clause, point, subpoint
        self.current_clause = None
        self.current_point = None
        self.current_subpoint = None
        return node

    def add_clause(self, number: str, text: str, block: TextBlock, confidence: float = 1.0) -> LegalASTNode:
        parent = self.current_article or self.current_section or self.current_chapter or self.root
        node = LegalASTNode(
            node_id=f"cls_{block.block_id}",
            node_type="clause",
            number=number,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=parent.node_id,
            source_block_ids=[block.block_id],
            confidence=confidence
        )
        parent.children.append(node)
        self.current_clause = node
        # Context Isolation: Reset point, subpoint
        self.current_point = None
        self.current_subpoint = None
        return node

    def add_point(self, number: str, text: str, block: TextBlock, confidence: float = 1.0) -> LegalASTNode:
        parent = self.current_clause or self.current_article or self.root
        node = LegalASTNode(
            node_id=f"pt_{block.block_id}",
            node_type="point",
            number=number,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=parent.node_id,
            source_block_ids=[block.block_id],
            confidence=confidence
        )
        parent.children.append(node)
        self.current_point = node
        # Context Isolation: Reset subpoint
        self.current_subpoint = None
        return node

    def add_preamble(self, block: TextBlock) -> LegalASTNode:
        if not self.current_preamble:
            node = LegalASTNode(
                node_id=f"preamble_{block.block_id}",
                node_type="preamble",
                raw_text=block.raw_text,
                normalized_text=block.normalized_text,
                parent_id=self.root.node_id,
                source_block_ids=[block.block_id]
            )
            self.root.children.insert(0, node)
            self.current_preamble = node
        else:
            self.current_preamble.raw_text += "\n" + block.raw_text
            self.current_preamble.normalized_text += "\n" + block.normalized_text
            self.current_preamble.source_block_ids.append(block.block_id)
        return self.current_preamble

    def add_appendix(self, number: str, title: str, block: TextBlock) -> LegalASTNode:
        node = LegalASTNode(
            node_id=f"app_{block.block_id}",
            node_type="appendix",
            number=number,
            title=title,
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=self.root.node_id,
            source_block_ids=[block.block_id]
        )
        self.root.children.append(node)
        self.current_appendix = node
        return node

    def add_signature(self, block: TextBlock) -> LegalASTNode:
        node = LegalASTNode(
            node_id=f"sig_{block.block_id}",
            node_type="signature",
            raw_text=block.raw_text,
            normalized_text=block.normalized_text,
            parent_id=self.root.node_id,
            source_block_ids=[block.block_id]
        )
        self.root.children.append(node)
        return node

    def append_text_to_active_node(self, block: TextBlock):
        target = (
            self.current_subpoint or
            self.current_point or
            self.current_clause or
            self.current_article or
            self.current_section or
            self.current_chapter or
            self.current_preamble or
            self.root
        )
        if target:
            if target.raw_text:
                target.raw_text += "\n" + block.raw_text
                target.normalized_text += "\n" + block.normalized_text
            else:
                target.raw_text = block.raw_text
                target.normalized_text = block.normalized_text
            target.source_block_ids.append(block.block_id)
