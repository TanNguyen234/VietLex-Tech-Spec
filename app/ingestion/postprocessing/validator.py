import hashlib
import re
from collections import Counter
from typing import Dict, List, Optional, Set

from app.ingestion.schemas import LegalASTNode, TextBlock, ValidationAuditResult


class StructureValidator:
    """
    Validation and integrity audit engine.

    The verified gate is block-based: every source block must be represented
    exactly once in AST-owned text, in source order, with legal hierarchy rules.
    """

    def validate(
        self,
        root: LegalASTNode,
        original_full_text: str = "",
        blocks: Optional[List[TextBlock]] = None,
        body_hash: Optional[str] = None,
    ) -> ValidationAuditResult:
        warnings: List[str] = []
        errors: List[str] = []
        missing_seqs: List[str] = []
        duplicate_nums: List[str] = []

        articles: List[LegalASTNode] = []
        self._collect_nodes_by_type(root, "article", articles)
        self._audit_article_numbering(articles, warnings, missing_seqs, duplicate_nums)
        self._audit_clause_numbering(articles, warnings)
        self._audit_hierarchy(root, errors)

        unresolved_blocks = list(root.unresolved_block_ids)
        if unresolved_blocks:
            errors.extend(f"UNRESOLVED_BLOCK: {item}" for item in unresolved_blocks)

        used_block_ids = self._collect_block_ids(root)
        usage = Counter(used_block_ids)
        expected_ids = [block.block_id for block in blocks] if blocks is not None else used_block_ids

        missing_ids = [block_id for block_id in expected_ids if usage.get(block_id, 0) == 0]
        duplicate_ids = [block_id for block_id, count in usage.items() if count > 1]

        if missing_ids:
            errors.append(f"MISSING_BLOCKS: {', '.join(missing_ids[:10])}")
        if duplicate_ids:
            errors.append(f"DUPLICATE_BLOCKS: {', '.join(duplicate_ids[:10])}")

        ordering_violations = self._ordering_violations(used_block_ids)
        if ordering_violations:
            errors.extend(ordering_violations[:10])

        source_text = "\n".join(block.normalized_text for block in blocks) if blocks is not None else self._clean_text(original_full_text)
        ast_text = self._concatenate_ast_text(root)
        char_count_raw = len(source_text)
        char_count_ast = len(ast_text)
        text_loss_pct = (len(missing_ids) / len(expected_ids) * 100.0) if expected_ids else 0.0

        raw_hash = self._hash_text(source_text)
        ast_hash = self._hash_text(ast_text)
        if body_hash and raw_hash != body_hash:
            warnings.append("BODY_HASH_INPUT_MISMATCH: validator source text hash differs from selected body hash")

        if errors:
            status = "FAIL"
        elif warnings:
            status = "WARNING"
        else:
            status = "PASS"

        return ValidationAuditResult(
            status=status,
            warnings=warnings,
            errors=errors,
            missing_sequences=missing_seqs,
            duplicate_numberings=duplicate_nums,
            unresolved_blocks=unresolved_blocks + missing_ids,
            char_count_raw=char_count_raw,
            char_count_ast=char_count_ast,
            text_loss_percentage=round(text_loss_pct, 2),
            raw_hash=raw_hash,
            ast_hash=ast_hash,
            block_coverage=dict(usage),
        )

    def _audit_article_numbering(
        self,
        articles: List[LegalASTNode],
        warnings: List[str],
        missing_seqs: List[str],
        duplicate_nums: List[str],
    ):
        article_numbers: List[int] = []
        seen_articles: Set[int] = set()

        for art in articles:
            if art.number and art.number.isdigit():
                num_int = int(art.number)
                if num_int in seen_articles:
                    duplicate_nums.append(f"Dieu {num_int}")
                    warnings.append(f"DUPLICATE_NUMBERING: Dieu {num_int} appears more than once")
                else:
                    seen_articles.add(num_int)
                    article_numbers.append(num_int)

        if article_numbers:
            min_num = min(article_numbers)
            max_num = max(article_numbers)
            for missing in sorted(set(range(min_num, max_num + 1)) - seen_articles):
                missing_seqs.append(f"Dieu {missing}")
                warnings.append(f"MISSING_SEQUENCE: missing Dieu {missing} between Dieu {min_num} and Dieu {max_num}")

    def _audit_clause_numbering(self, articles: List[LegalASTNode], warnings: List[str]):
        for art in articles:
            clauses: List[LegalASTNode] = []
            self._collect_nodes_by_type(art, "clause", clauses)
            clause_nums: Set[int] = set()
            for cls in clauses:
                if cls.number and cls.number.isdigit():
                    c_num = int(cls.number)
                    if c_num in clause_nums:
                        warnings.append(f"DUPLICATE_CLAUSE: clause {c_num} duplicated in article {art.number or ''}")
                    clause_nums.add(c_num)

    def _audit_hierarchy(self, root: LegalASTNode, errors: List[str]):
        node_by_id: Dict[str, LegalASTNode] = {}
        self._collect_node_map(root, node_by_id)

        for node in node_by_id.values():
            if node.node_type == "clause":
                parent = node_by_id.get(node.parent_id or "")
                if not parent or parent.node_type != "article":
                    errors.append(f"INVALID_HIERARCHY: clause {node.number or node.node_id} is not under an article")
            if node.node_type == "point":
                parent = node_by_id.get(node.parent_id or "")
                if not parent or parent.node_type != "clause":
                    errors.append(f"INVALID_HIERARCHY: point {node.number or node.node_id} is not under a clause")

    def _collect_nodes_by_type(self, node: LegalASTNode, target_type: str, result: List[LegalASTNode]):
        if node.node_type == target_type:
            result.append(node)
        for child in node.children:
            self._collect_nodes_by_type(child, target_type, result)

    def _collect_node_map(self, node: LegalASTNode, result: Dict[str, LegalASTNode]):
        result[node.node_id] = node
        for child in node.children:
            self._collect_node_map(child, result)

    def _collect_block_ids(self, root: LegalASTNode) -> List[str]:
        block_ids: List[str] = []

        def visit(node: LegalASTNode):
            block_ids.extend(node.source_block_ids)
            for child in node.children:
                visit(child)

        visit(root)
        return block_ids

    def _ordering_violations(self, block_ids: List[str]) -> List[str]:
        orders: List[int] = []
        for block_id in block_ids:
            match = re.search(r"_(\d+)$", block_id)
            if match:
                orders.append(int(match.group(1)))

        violations = []
        for idx in range(len(orders) - 1):
            if orders[idx] > orders[idx + 1]:
                violations.append(f"ORDERING_VIOLATION: block order {orders[idx]} appears before {orders[idx + 1]}")
        return violations

    def _concatenate_ast_text(self, node: LegalASTNode) -> str:
        texts = []
        if node.normalized_text:
            texts.append(node.normalized_text)
        for child in node.children:
            child_str = self._concatenate_ast_text(child)
            if child_str:
                texts.append(child_str)
        return "\n".join(texts)

    def _clean_text(self, text: str) -> str:
        return "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
