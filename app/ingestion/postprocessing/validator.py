from typing import List, Dict, Set
from app.ingestion.schemas import LegalASTNode, ValidationAuditResult

class StructureValidator:
    """
    Validation & Integrity Audit Engine (Phase 5).
    Audits numbering sequence, duplicate headers, structural hierarchy, and text loss.
    """

    def validate(self, root: LegalASTNode, original_full_text: str) -> ValidationAuditResult:
        warnings: List[str] = []
        errors: List[str] = []
        missing_seqs: List[str] = []
        duplicate_nums: List[str] = []
        unresolved_blocks: List[str] = []

        # 1. Collect articles, clauses, points
        articles: List[LegalASTNode] = []
        self._collect_nodes_by_type(root, "article", articles)

        # Audit Article Numbering
        article_numbers: List[int] = []
        seen_articles: Set[int] = set()

        for art in articles:
            if art.number and art.number.isdigit():
                num_int = int(art.number)
                if num_int in seen_articles:
                    duplicate_nums.append(f"Điều {num_int}")
                    warnings.append(f"DUPLICATE_NUMBERING: Điều {num_int} xuất hiện nhiều lần")
                else:
                    seen_articles.add(num_int)
                    article_numbers.append(num_int)

        # Check sequence continuity
        if article_numbers:
            min_num = min(article_numbers)
            max_num = max(article_numbers)
            expected_set = set(range(min_num, max_num + 1))
            missing = expected_set - seen_articles
            for m in sorted(list(missing)):
                missing_seqs.append(f"Điều {m}")
                warnings.append(f"MISSING_SEQUENCE: Thiếu Điều {m} trong dãy từ Điều {min_num} đến Điều {max_num}")

        # Audit Clause Numbering inside each Article
        for art in articles:
            clauses: List[LegalASTNode] = []
            self._collect_nodes_by_type(art, "clause", clauses)
            clause_nums: Set[int] = set()
            for cls in clauses:
                if cls.number and cls.number.isdigit():
                    c_num = int(cls.number)
                    if c_num in clause_nums:
                        warnings.append(f"DUPLICATE_CLAUSE: Khoản {c_num} trùng lặp trong {art.number or 'Điều'}")
                    clause_nums.add(c_num)

        # Audit Hierarchy (Orphan Points)
        points: List[LegalASTNode] = []
        self._collect_nodes_by_type(root, "point", points)
        for pt in points:
            if not pt.parent_id or "cls_" not in pt.parent_id:
                warnings.append(f"ORPHAN_POINT: Điểm {pt.number or ''} xuất hiện ngoài Khoản")

        # 2. Audit Text Loss
        ast_text = self._concatenate_ast_text(root)
        clean_raw_text = "\n".join([line.strip() for line in original_full_text.splitlines() if line.strip()])
        char_count_raw = len(clean_raw_text)
        char_count_ast = len(ast_text)

        loss_chars = max(0, char_count_raw - char_count_ast)
        text_loss_pct = (loss_chars / char_count_raw * 100.0) if char_count_raw > 0 else 0.0

        if text_loss_pct > 5.0:
            errors.append(f"CRITICAL_TEXT_LOSS: Mất mát {text_loss_pct:.2f}% văn bản gốc ({loss_chars} ký tự)")
            status = "FAIL"
        elif text_loss_pct > 1.0 or warnings:
            status = "WARNING"
        else:
            status = "PASS"

        return ValidationAuditResult(
            status=status,
            warnings=warnings,
            errors=errors,
            missing_sequences=missing_seqs,
            duplicate_numberings=duplicate_nums,
            unresolved_blocks=unresolved_blocks,
            char_count_raw=char_count_raw,
            char_count_ast=char_count_ast,
            text_loss_percentage=round(text_loss_pct, 2)
        )

    def _collect_nodes_by_type(self, node: LegalASTNode, target_type: str, result: List[LegalASTNode]):
        if node.node_type == target_type:
            result.append(node)
        for child in node.children:
            self._collect_nodes_by_type(child, target_type, result)

    def _concatenate_ast_text(self, node: LegalASTNode) -> str:
        texts = []
        if node.raw_text:
            texts.append(node.raw_text)
        for child in node.children:
            child_str = self._concatenate_ast_text(child)
            if child_str:
                texts.append(child_str)
        return "\n".join(texts)
