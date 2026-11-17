"""Remove echoed evidence headers that the model sometimes copies into the answer body."""

from __future__ import annotations

import re

from app.services.legal_topic_terms import fold_topic_text

_ECHO_LABEL = "doan mo dau khong danh so"


def strip_context_echo(answer: str) -> str:
    """Drop an 'unnumbered opening paragraph' label and the blockquote that follows it.

    The model occasionally quotes a retrieved article header as a trailing block such as
    "**Đoạn mở đầu không đánh số — [45/2019/QH14, Điều 40]:**" followed by "> Điều 40. ...".
    That block is not part of the answer and carries an unrelated citation, so it is removed.
    """
    text = str(answer or "")
    if _ECHO_LABEL not in fold_topic_text(text):
        return text
    kept: list[str] = []
    skipping = False
    for line in text.split("\n"):
        if _ECHO_LABEL in fold_topic_text(line):
            skipping = True
            continue
        if skipping:
            if not line.strip() or line.lstrip().startswith(">"):
                continue
            skipping = False
        kept.append(line)
    cleaned = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
