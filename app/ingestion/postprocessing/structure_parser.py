import re
from typing import List, Optional
from app.ingestion.schemas import TextBlock, LegalASTNode
from app.ingestion.postprocessing.state_machine import DeterministicStateMachine

class StructureParser:
    """
    Deterministic Legal Structure Parser (Phase 4).
    Parses ordered TextBlocks into a complete Legal AST using regex patterns and StateMachine.
    """

    def __init__(self):
        # Patterns for structural elements
        self.re_chapter = re.compile(r'^\s*CHƯƠNG\s+([A-Za-z0-9_À-ỹ]+)(?:[\.\:\-]\s*(.*))?$', re.IGNORECASE)
        self.re_section = re.compile(r'^\s*MỤC\s+([A-Za-z0-9_À-ỹ]+)(?:[\.\:\-]\s*(.*))?$', re.IGNORECASE)
        self.re_article = re.compile(r'^\s*Điều\s+([0-9]+)[\.\:]?\s*(.*)$', re.IGNORECASE)
        self.re_clause = re.compile(r'^\s*([0-9]+)\.\s+(.*)$')
        self.re_point = re.compile(r'^\s*([a-zđA-ZĐ])\)\s+(.*)$')
        self.re_appendix = re.compile(r'^\s*PHỤ LỤC\s*([0-9IVXLCDM]*)(?:[\.\:\-]\s*(.*))?$', re.IGNORECASE)
        self.re_signature = re.compile(r'^\s*(Nơi nhận:|TM\.\s*CHÍNH PHỦ|THỦ TƯỚNG|BỘ TRƯỞNG|CHỦ TỊCH|KÝ THAY|KT\.)', re.IGNORECASE)

    def parse(self, blocks: List[TextBlock], doc_title: str = "Legal Document") -> LegalASTNode:
        sm = DeterministicStateMachine(doc_title=doc_title)
        
        i = 0
        n = len(blocks)

        while i < n:
            block = blocks[i]
            text = block.normalized_text.strip()

            if not text:
                i += 1
                continue

            # Check Signature block near the end
            if i >= n - 10 and self.re_signature.match(text):
                sm.add_signature(block)
                i += 1
                continue

            # Check Appendix
            match_app = self.re_appendix.match(text)
            if match_app:
                num = match_app.group(1).strip()
                title = match_app.group(2).strip() if match_app.group(2) else ""
                sm.add_appendix(num, title, block)
                i += 1
                continue

            # Check Chapter
            match_chap = self.re_chapter.match(text)
            if match_chap:
                num = match_chap.group(1).strip()
                title = match_chap.group(2).strip() if match_chap.group(2) else ""
                title_block = None
                # Lookahead if title is on next block
                if not title and i + 1 < n:
                    next_text = blocks[i+1].normalized_text.strip()
                    if next_text and next_text.isupper() and not self.is_structural_candidate(next_text):
                        title = next_text
                        title_block = blocks[i+1]
                        i += 1
                chap_node = sm.add_chapter(num, title, block)
                if title_block:
                    chap_node.raw_text += "\n" + title_block.raw_text
                    chap_node.normalized_text += "\n" + title_block.normalized_text
                    chap_node.source_block_ids.append(title_block.block_id)
                i += 1
                continue

            # Check Section
            match_sec = self.re_section.match(text)
            if match_sec:
                num = match_sec.group(1).strip()
                title = match_sec.group(2).strip() if match_sec.group(2) else ""
                title_block = None
                if not title and i + 1 < n:
                    next_text = blocks[i+1].normalized_text.strip()
                    if next_text and next_text.isupper() and not self.is_structural_candidate(next_text):
                        title = next_text
                        title_block = blocks[i+1]
                        i += 1
                sec_node = sm.add_section(num, title, block)
                if title_block:
                    sec_node.raw_text += "\n" + title_block.raw_text
                    sec_node.normalized_text += "\n" + title_block.normalized_text
                    sec_node.source_block_ids.append(title_block.block_id)
                i += 1
                continue

            # Check Article
            match_art = self.re_article.match(text)
            if match_art and not self.is_citation_reference(text):
                num = match_art.group(1).strip()
                title = match_art.group(2).strip() if match_art.group(2) else ""
                sm.add_article(num, title, block)
                i += 1
                continue

            # Check Clause
            match_cls = self.re_clause.match(text)
            if match_cls and not self.is_citation_reference(text):
                # Ensure we have active article context or clause starts a numbered item
                num = match_cls.group(1).strip()
                clause_text = match_cls.group(2).strip()
                sm.add_clause(num, clause_text, block)
                i += 1
                continue

            # Check Point
            match_pt = self.re_point.match(text)
            if match_pt and not self.is_citation_reference(text):
                num = match_pt.group(1).strip()
                pt_text = match_pt.group(2).strip()
                sm.add_point(num, pt_text, block)
                i += 1
                continue

            # Default: Preamble (if before first chapter/article) or content text appended to active node
            if sm.current_article is None and sm.current_chapter is None and sm.current_section is None:
                sm.add_preamble(block)
            else:
                sm.append_text_to_active_node(block)

            i += 1

        return sm.root

    def is_structural_candidate(self, text: str) -> bool:
        return bool(
            self.re_chapter.match(text) or
            self.re_section.match(text) or
            self.re_article.match(text) or
            self.re_appendix.match(text)
        )

    def is_citation_reference(self, text: str) -> bool:
        """Checks if the block is a citation/reference line rather than a structural heading."""
        text_lower = text.lower()
        citation_keywords = ["theo khoản", "căn cứ khoản", "quy định tại khoản", "tại điều", "theo điều", "quy định tại điều"]
        for kw in citation_keywords:
            if kw in text_lower:
                return True
        return False
