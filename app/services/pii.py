from __future__ import annotations

import re


def redact_pii(text: str) -> str:
    if not text:
        return text
    text = re.sub(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "[EMAIL_ĐÃ_ẨN]",
        text,
    )
    text = re.sub(r"(?:\+?84|0)[35789]\d{8}\b", "[SĐT_ĐÃ_ẨN]", text)
    return re.sub(r"\b(?:\d{12}|\d{9})\b", "[CCCD_ĐÃ_ẨN]", text)
