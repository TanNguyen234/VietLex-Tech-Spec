from app.services.primary_law_rescue import _LABOR, _is_explicitly_scoped, _planned_titles


def test_notice_period_question_plans_current_labor_code():
    query = "Người lao động đơn phương chấm dứt hợp đồng không xác định thời hạn phải báo trước bao nhiêu ngày?"
    assert _LABOR in _planned_titles(query)


def test_annual_leave_question_plans_current_labor_code():
    query = "Người làm đủ 12 tháng được nghỉ hằng năm bao nhiêu ngày?"
    assert _LABOR in _planned_titles(query)


def test_unrelated_question_does_not_plan_labor_code():
    query = "Thủ tục đăng ký kinh doanh cho hộ kinh doanh là gì?"
    assert _LABOR not in _planned_titles(query)


def test_generic_vietnam_or_current_law_phrase_does_not_block_primary_rescue():
    for phrase in (
        "Theo luật Việt Nam, thời gian thử việc tối đa là bao nhiêu?",
        "Theo luật hiện nay, mức lương thử việc tối thiểu là bao nhiêu?",
        "Theo luật khác có liên quan, thời gian thử việc thế nào?",
    ):
        assert not _is_explicitly_scoped(phrase, (_LABOR,))
