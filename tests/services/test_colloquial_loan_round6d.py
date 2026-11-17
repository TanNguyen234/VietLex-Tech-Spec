"""Round-6d colloquial loan wording: 'đưa bạn vay', 'không lập văn bản', 'đem ra tòa' and 'giờ đòi không được'
map to the legal terms used in the corpus, so the Q6b question retrieves BLDS 2015 Điều 119 and BLTTDS 2015
Điều 190–192 instead of off-topic official supplements. Output-guard behaviour is unchanged."""

from app.services.legal_topic_terms import normalize_colloquial_query


def test_q6b_colloquial_loan_question_uses_corpus_legal_terms():
    text = normalize_colloquial_query(
        "tôi đưa bạn vay 50 triệu không lập văn bản, giờ đòi không được, có đem ra tòa được không?"
    )

    assert "cho vay" in text
    assert "không lập thành văn bản" in text
    assert "đòi nợ không được trả" in text
    assert "khởi kiện ra Tòa án" in text
    assert "đưa bạn vay" not in text


def test_existing_loan_wording_is_unchanged():
    question = "cho bạn mượn 50 triệu bằng miệng, không có giấy gì, bạn không trả thì có khởi kiện được không?"

    assert normalize_colloquial_query(question) == question


def test_unrelated_dua_phrase_is_not_rewritten():
    text = normalize_colloquial_query("đưa bạn về nhà lúc tối thì có bị phạt không?")

    assert "cho vay" not in text
    assert text == "đưa bạn về nhà lúc tối thì có bị phạt không?"
