"""Carry at most one user-authored situation for an explicit follow-up.

Callers must supply owner-scoped history. Assistant answers are never facts.
"""
import re
from collections.abc import Mapping, Sequence

from app.services.legal_topic_terms import extract_official_topic_phrases, fold_topic_text
from app.services.pii import redact_pii


def is_explicit_followup(query: str) -> bool:
    folded = fold_topic_text(query)
    return bool(re.search(
        r'^vay\b|\b(?:the neu|hoi tiep|nhu tren|o tren|tinh huong truoc|truoc do)\b'
        r'|\b(?:muc luong(?: cong viec)?|cong viec|tinh huong|hop dong) do\b',
        folded,
    ))


def followup_context(query: str, history: Sequence[Mapping]) -> str | None:
    if not is_explicit_followup(query):
        return None
    topics = set(extract_official_topic_phrases(query, limit=8))
    recent = list(history[-8:])
    # With no named topic, only the immediately preceding user turn is eligible.
    if not topics:
        recent = recent[-1:]
    for message in reversed(recent):
        previous = str(message.get('user_query') or '')[:1000]
        if not previous or previous == query:
            continue
        previous_topics = set(extract_official_topic_phrases(previous, limit=8))
        if previous_topics and (not topics or topics.intersection(previous_topics)):
            return redact_pii(previous)
    return None
