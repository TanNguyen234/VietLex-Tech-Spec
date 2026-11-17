"""Round-6e: a loan or debt-claim question also rescues the BLDS 2015 limitation-period text (Điều 429, 3 years),
not only the general loan rules. Non-loan questions do not gain the limitation rule."""

import re

from app.services import primary_law_rescue as rescue
from app.services.legal_topic_terms import fold_topic_text


def _matching_phrases(query: str) -> list[str]:
    folded = fold_topic_text(query)
    hits: list[str] = []
    for pattern, phrases in rescue._CIVIL_GENERAL.domain_rules:
        if re.search(pattern, folded):
            hits.extend(phrases)
    return hits


def test_loan_claim_question_rescues_three_year_limitation_rule():
    question = (
        "tôi cho vay 50 triệu không lập thành văn bản, đòi nợ không được trả, "
        "có khởi kiện ra Tòa án được không?"
    )

    hits = _matching_phrases(question)

    assert "thoi hieu khoi kien ve hop dong" in hits
    assert "03 nam" in hits


def test_non_loan_question_does_not_gain_limitation_rule():
    question = "công ty sa thải tôi thì tôi có được trợ cấp hay bồi thường không?"

    assert "03 nam" not in _matching_phrases(question)
