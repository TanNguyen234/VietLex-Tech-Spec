import re
import unicodedata
from typing import List

from app.ingestion.schemas import LegalASTNode, TextBlock
from app.ingestion.postprocessing.state_machine import DeterministicStateMachine


class StructureParser:
    """
    Deterministic legal structure parser.

    Matching is performed on an accent-folded copy of each block so fixtures can
    stay hermetic and ASCII while production Vietnamese text still parses.
    """

    def __init__(self):
        self.re_chapter = re.compile(r"^\s*chuong\s+([A-Za-z0-9_À-ỹ]+)(?:[\.\:\-]\s*(.*))?$", re.IGNORECASE)
        self.re_section = re.compile(r"^\s*muc\s+([A-Za-z0-9_À-ỹ]+)(?:[\.\:\-]\s*(.*))?$", re.IGNORECASE)
        self.re_article = re.compile(r"^\s*dieu\s+([0-9]+)[\.\:]?\s*(.*)$", re.IGNORECASE)
        self.re_clause = re.compile(r"^\s*([0-9]+)\.\s+(.*)$")
        self.re_point = re.compile(r"^\s*([a-zdA-ZD])\)\s+(.*)$")
        self.re_appendix = re.compile(r"^\s*phu\s+luc\s*([0-9IVXLCDM]*)(?:[\.\:\-]\s*(.*))?$", re.IGNORECASE)
        self.re_signature = re.compile(
            r"^\s*(noi nhan:|tm\.\s*chinh phu|thu tuong|bo truong|chu tich|ky thay|kt\.)",
            re.IGNORECASE,
        )

    def parse(
        self,
        blocks: List[TextBlock],
        doc_title: str = "Legal Document",
        document_id: str = "doc_unk",
    ) -> LegalASTNode:
        sm = DeterministicStateMachine(doc_title=doc_title, document_id=document_id)

        i = 0
        n = len(blocks)
        while i < n:
            block = blocks[i]
            text = block.normalized_text.strip()
            folded_text = self._fold_text(text)

            if not text:
                i += 1
                continue

            if i >= n - 10 and self.re_signature.match(folded_text):
                sm.add_signature(block)
                i += 1
                continue

            match_app = self.re_appendix.match(folded_text)
            if match_app:
                num = match_app.group(1).strip()
                title = self._folded_group(match_app, 2)
                sm.add_appendix(num, title, block)
                i += 1
                continue

            match_chap = self.re_chapter.match(folded_text)
            if match_chap:
                num = match_chap.group(1).strip()
                title = self._folded_group(match_chap, 2)
                title_block = None
                if not title and i + 1 < n:
                    next_text = blocks[i + 1].normalized_text.strip()
                    if next_text and next_text.isupper() and not self.is_structural_candidate(next_text):
                        title = next_text
                        title_block = blocks[i + 1]
                        i += 1
                chap_node = sm.add_chapter(num, title, block)
                if title_block:
                    self._append_block_text(chap_node, title_block)
                i += 1
                continue

            match_sec = self.re_section.match(folded_text)
            if match_sec:
                num = match_sec.group(1).strip()
                title = self._folded_group(match_sec, 2)
                title_block = None
                if not title and i + 1 < n:
                    next_text = blocks[i + 1].normalized_text.strip()
                    if next_text and next_text.isupper() and not self.is_structural_candidate(next_text):
                        title = next_text
                        title_block = blocks[i + 1]
                        i += 1
                sec_node = sm.add_section(num, title, block)
                if title_block:
                    self._append_block_text(sec_node, title_block)
                i += 1
                continue

            match_art = self.re_article.match(folded_text)
            if match_art and not self.is_citation_reference(text):
                num = match_art.group(1).strip()
                title = self._folded_group(match_art, 2)
                sm.add_article(num, title, block)
                i += 1
                continue

            match_cls = self.re_clause.match(text)
            if match_cls and not self.is_citation_reference(text):
                if sm.current_article is None:
                    sm.add_unresolved(block, "CLAUSE_WITHOUT_ARTICLE")
                    i += 1
                    continue
                num = match_cls.group(1).strip()
                clause_text = match_cls.group(2).strip()
                sm.add_clause(num, clause_text, block)
                i += 1
                continue

            match_pt = self.re_point.match(folded_text)
            if match_pt and not self.is_citation_reference(text):
                if sm.current_clause is None:
                    sm.add_unresolved(block, "POINT_WITHOUT_CLAUSE")
                    i += 1
                    continue
                num = match_pt.group(1).strip()
                point_text = match_pt.group(2).strip()
                sm.add_point(num, point_text, block)
                i += 1
                continue

            if sm.current_article is None and sm.current_chapter is None and sm.current_section is None and sm.current_appendix is None:
                sm.add_preamble(block)
            else:
                sm.append_text_to_active_node(block)

            i += 1

        return sm.root

    def is_structural_candidate(self, text: str) -> bool:
        folded_text = self._fold_text(text)
        return bool(
            self.re_chapter.match(folded_text)
            or self.re_section.match(folded_text)
            or self.re_article.match(folded_text)
            or self.re_appendix.match(folded_text)
        )

    def is_citation_reference(self, text: str) -> bool:
        folded_text = self._fold_text(text)
        citation_keywords = [
            "theo khoan",
            "can cu khoan",
            "quy dinh tai khoan",
            "tai dieu",
            "theo dieu",
            "quy dinh tai dieu",
        ]
        return any(keyword in folded_text for keyword in citation_keywords)

    def _append_block_text(self, node: LegalASTNode, block: TextBlock):
        node.raw_text += "\n" + block.raw_text
        node.normalized_text += "\n" + block.normalized_text
        node.source_block_ids.append(block.block_id)

    def _folded_group(self, match: re.Match, index: int) -> str:
        value = match.group(index) if match.lastindex and match.lastindex >= index else ""
        return value.strip() if value else ""

    def _fold_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFD", text or "")
        without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return without_marks.replace("đ", "d").replace("Đ", "D").lower()
