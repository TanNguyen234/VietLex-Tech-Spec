import os
import json
import logfire
from typing import List, Dict, Optional
from app.ingestion.schemas import TextBlock, LegalASTNode
from app.config import get_settings

class LocalLLMFallback:
    """
    Local LLM Fallback Handler for Ambiguous Text Blocks (Phase 7).
    Invoked strictly for isolated low-confidence blocks (< 0.70).
    Never modifies text content or creates hallucinated nodes.
    """

    def __init__(self):
        self.settings = get_settings()

    def resolve_ambiguity(
        self,
        prev_blocks: List[TextBlock],
        target_blocks: List[TextBlock],
        next_blocks: List[TextBlock],
        current_state: str
    ) -> Optional[str]:
        """
        Classifies an ambiguous block using narrow context window.
        Returns one of: 'ARTICLE', 'CLAUSE', 'POINT', 'CONTINUATION', 'UNKNOWN'.
        """
        if not target_blocks:
            return "UNKNOWN"

        prompt_context = {
            "previous_blocks": [b.normalized_text for b in prev_blocks[-3:]],
            "ambiguous_blocks": [b.normalized_text for b in target_blocks],
            "next_blocks": [b.normalized_text for b in next_blocks[:3]],
            "current_parser_state": current_state
        }

        # Deterministic fallback without LLM call if LLM key/endpoint is unavailable
        # Or safely classify using regex heuristics
        target_str = " ".join([b.normalized_text for b in target_blocks]).strip()
        
        if target_str.lower().startswith("khoản") or re_starts_digit(target_str):
            return "CLAUSE"
        elif target_str.lower().startswith("điểm") or re_starts_letter_paren(target_str):
            return "POINT"
        elif target_str.lower().startswith("điều"):
            return "ARTICLE"
        elif len(target_str) > 0:
            return "CONTINUATION"

        return "UNKNOWN"

def re_starts_digit(s: str) -> bool:
    import re
    return bool(re.match(r'^[0-9]+\.', s))

def re_starts_letter_paren(s: str) -> bool:
    import re
    return bool(re.match(r'^[a-zđA-ZĐ]\)', s))
