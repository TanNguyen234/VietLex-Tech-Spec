from app.ingestion.schemas import LegalASTNode

class ConfidenceScorer:
    """
    Deterministic Confidence Scoring Engine (Phase 6).
    Calculates confidence scores for each AST node based on regex match, sequence continuity,
    and parent-child structural alignment.
    """

    def score_ast(self, root: LegalASTNode):
        self._score_node(root)

    def _score_node(self, node: LegalASTNode):
        if node.node_type == "document":
            node.confidence = 1.0
        elif node.node_type in ["chapter", "section"]:
            if node.number and node.title:
                node.confidence = 0.98
            elif node.number:
                node.confidence = 0.90
            else:
                node.confidence = 0.75
        elif node.node_type == "article":
            if node.number and node.number.isdigit():
                node.confidence = 0.99
            else:
                node.confidence = 0.85
        elif node.node_type == "clause":
            if node.number and node.number.isdigit() and node.parent_id and "art_" in node.parent_id:
                node.confidence = 0.98
            elif node.number:
                node.confidence = 0.85
            else:
                node.confidence = 0.65
        elif node.node_type == "point":
            if node.number and len(node.number) == 1 and node.parent_id and "cls_" in node.parent_id:
                node.confidence = 0.95
            else:
                node.confidence = 0.70
        elif node.node_type in ["preamble", "appendix", "signature"]:
            node.confidence = 0.90
        else:
            node.confidence = 0.50

        # Recursively score children
        for child in node.children:
            self._score_node(child)
