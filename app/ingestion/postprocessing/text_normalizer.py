import re
import unicodedata
import html
from typing import List, Optional
from bs4 import BeautifulSoup
from app.ingestion.schemas import TextBlock

class TextNormalizer:
    """
    Generic HTML Normalizer & Text Block Builder (Phase 3).
    Converts full_text and html_text into clean, ordered TextBlock instances.
    """

    def __init__(self):
        pass

    def normalize_text(self, text: str) -> str:
        if not text:
            return ""
        # Decode HTML entities
        text = html.unescape(text)
        # Unicode normalization (NFC)
        text = unicodedata.normalize("NFC", text)
        # Clean non-breaking spaces and zero-width spaces
        text = text.replace("\xa0", " ").replace("\u200b", "")
        # Remove consecutive trailing/leading spaces on lines
        lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
        return "\n".join(lines).strip()

    def build_text_blocks(self, full_text: str, html_text: Optional[str] = None, source: Optional[str] = None) -> List[TextBlock]:
        blocks: List[TextBlock] = []

        if html_text and html_text.strip():
            blocks = self._build_blocks_from_html(html_text, source)

        if not blocks and full_text and full_text.strip():
            blocks = self._build_blocks_from_plain_text(full_text, source)

        return blocks

    def _build_blocks_from_html(self, html_text: str, source: Optional[str]) -> List[TextBlock]:
        blocks: List[TextBlock] = []
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            # Strip script, style, meta tags
            for elem in soup(["script", "style", "meta", "noscript", "footer", "nav"]):
                elem.decompose()

            raw_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'tr', 'li'])
            order = 0

            for el in raw_elements:
                # If element has child block tags, skip parent to avoid duplicate blocks
                if el.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'li']):
                    continue

                raw_t = el.get_text()
                norm_t = self.normalize_text(raw_t)

                if not norm_t:
                    continue

                order += 1
                tag_name = el.name
                dom_path = self._get_dom_path(el)

                blocks.append(TextBlock(
                    block_id=f"block_{order:06d}",
                    order=order,
                    raw_text=raw_t,
                    normalized_text=norm_t,
                    source_tag=tag_name,
                    dom_path=dom_path,
                    source=source
                ))
        except Exception:
            pass

        return blocks

    def _build_blocks_from_plain_text(self, full_text: str, source: Optional[str]) -> List[TextBlock]:
        blocks: List[TextBlock] = []
        norm_full = self.normalize_text(full_text)
        raw_paragraphs = [p.strip() for p in norm_full.split("\n") if p.strip()]

        order = 0
        for p in raw_paragraphs:
            order += 1
            blocks.append(TextBlock(
                block_id=f"block_{order:06d}",
                order=order,
                raw_text=p,
                normalized_text=p,
                source_tag="p",
                dom_path=None,
                source=source
            ))

        return blocks

    def _get_dom_path(self, element) -> str:
        components = []
        child = element
        for parent in child.parents:
            if parent is None or parent.name == '[document]':
                break
            siblings = parent.find_all(child.name, recursive=False)
            index = siblings.index(child) + 1 if len(siblings) > 1 else 1
            components.append(f"{child.name}[{index}]")
            child = parent
        components.reverse()
        return "/" + "/".join(components)
