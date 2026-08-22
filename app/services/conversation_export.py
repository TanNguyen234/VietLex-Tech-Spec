from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


def _escape_heading(value: str) -> str:
    return value.replace("\\", "\\\\").replace("#", "\\#").strip()


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return "Không rõ thời gian"


def render_conversation_markdown(
    session: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]
) -> str:
    title = _escape_heading(str(session.get("title") or "Hội thoại VietLex"))
    lines = [f"# {title}", ""]
    for message in messages:
        lines.extend(
            [
                f"*{_timestamp(message.get('timestamp'))}*",
                f"**Trace:** `{message.get('trace_id') or 'N/A'}`",
                "",
                "## Người dùng",
                "",
                str(message.get("user_query") or ""),
                "",
                "## VietLex",
                "",
                str(message.get("bot_response") or ""),
                "",
            ]
        )
        contexts = message.get("contexts") or []
        if contexts:
            lines.extend(["### Nguồn tham chiếu", ""])
            for context in contexts:
                quoted = str(context).replace("\r\n", "\n").replace("\r", "\n")
                lines.extend([*(f"> {line}" for line in quoted.split("\n")), ""])
        lines.extend(["---", ""])
    return "\n".join(lines).rstrip() + "\n"
