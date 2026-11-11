from app.services.citation_clause_guard import correct_clause_citations

CONTEXT_THU_VIEC = (
    "[45/2019/QH14, Điều 25] | Nguồn: https://example.test/blld-2019 | Tiêu đề: Bộ luật Lao động 2019\n"
    "Điều 25. Thời gian thử việc\n"
    "1. Thời gian thử việc không quá 180 ngày đối với người quản lý doanh nghiệp; "
    "không quá 60 ngày đối với công việc cần trình độ cao đẳng trở lên.\n"
    "2. Thời gian thử việc chỉ được thỏa thuận một lần đối với một công việc.\n"
)
CONTEXT_DON_PHUONG = (
    "[45/2019/QH14, Điều 35] | Tiêu đề: Bộ luật Lao động 2019\n"
    "Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động của người lao động\n"
    "1. Người lao động phải báo trước cho người sử dụng lao động như sau:\n"
    "a) Ít nhất 45 ngày đối với hợp đồng lao động không xác định thời hạn;\n"
    "b) Ít nhất 30 ngày đối với hợp đồng lao động xác định thời hạn từ 12 tháng đến 36 tháng.\n"
    "2. Trường hợp đặc biệt được quy định tại Điều 35 này.\n"
)


def test_wrong_clause_is_corrected_when_only_one_clause_holds_the_number():
    answer = (
        "Theo **Khoản 2 Điều 25 Bộ luật Lao động 2019** (dẫn nguồn [45/2019/QH14, Điều 25]):\n\n"
        "Thời gian thử việc tối đa là **không quá 60 ngày**.\n"
    )
    corrected, changes = correct_clause_citations(answer, [CONTEXT_THU_VIEC])
    assert "Khoản 1 Điều 25 Bộ luật Lao động 2019" in corrected
    assert "Khoản 2 Điều 25" not in corrected
    assert changes == [{"article": "25", "from_clause": "2", "to_clause": "1", "numbers": ["60 ngày"]}]


def test_correct_clause_is_left_unchanged():
    answer = "Theo **Khoản 1 Điều 25 Bộ luật Lao động 2019**, không quá **60 ngày**."
    corrected, changes = correct_clause_citations(answer, [CONTEXT_THU_VIEC])
    assert corrected == answer
    assert changes == []


def test_unsupported_number_is_not_rewritten():
    answer = "Theo **Khoản 2 Điều 25**, thời hạn là **999 ngày**."
    corrected, changes = correct_clause_citations(answer, [CONTEXT_THU_VIEC])
    assert corrected == answer
    assert changes == []


def test_notice_period_clause_is_corrected_from_article_35():
    answer = "Người lao động báo trước **ít nhất 45 ngày** theo **Khoản 2 Điều 35 BLLĐ 2019**."
    corrected, changes = correct_clause_citations(answer, [CONTEXT_DON_PHUONG])
    assert "Khoản 1 Điều 35 BLLĐ 2019" in corrected
    assert changes[0]["to_clause"] == "1"


def test_claim_before_citation_with_parenthetical_reference_is_used():
    answer = (
        "Thời gian thử việc tối đa là **không quá 60 ngày** (theo quy định tại đoạn mở đầu Điều 25 và "
        "**Khoản 2 Điều 25** Bộ luật Lao động 2019 [Tài liệu tham khảo #1])."
    )
    corrected, changes = correct_clause_citations(answer, [CONTEXT_THU_VIEC])
    assert "**Khoản 1 Điều 25** Bộ luật Lao động 2019" in corrected
    assert changes[0]["to_clause"] == "1"


def test_no_contexts_means_no_change():
    answer = "Theo **Khoản 2 Điều 25**, không quá **60 ngày**."
    assert correct_clause_citations(answer, []) == (answer, [])


def test_cross_document_same_article_is_disambiguated_by_nearby_doc_number():
    context_doc_a = (
        "[45/2019/QH14, Điều 25]\n"
        "Điều 25. Thời gian thử việc\n"
        "1. Không quá 60 ngày đối với công việc cao đẳng.\n"
        "2. Không quá 30 ngày đối với công việc trung cấp.\n"
    )
    context_doc_b = (
        "[145/2020/NĐ-CP, Điều 25]\n"
        "Điều 25. Thủ tục báo cáo\n"
        "1. Thời hạn 15 ngày.\n"
        "2. Thời hạn 60 ngày kể từ ngày kết thúc.\n"
    )
    answer = (
        "Theo **Khoản 2 Điều 25** của văn bản 45/2019/QH14, thời gian thử việc "
        "không quá **60 ngày**."
    )
    corrected, changes = correct_clause_citations(answer, [context_doc_a, context_doc_b])
    assert "Khoản 1 Điều 25" in corrected
    assert changes[0]["to_clause"] == "1"


def test_next_paragraph_with_own_citation_does_not_bleed_into_previous_citation():
    answer = (
        "Theo **Khoản 2 Điều 25 Bộ luật Lao động 2019**, thời gian thử việc chỉ được thỏa thuận một lần.\n\n"
        "Theo Khoản 1 Điều 25, thời gian thử việc không quá 60 ngày."
    )
    corrected, changes = correct_clause_citations(answer, [CONTEXT_THU_VIEC])
    assert corrected == answer
    assert changes == []
