from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def test_group_breakdown_distinguishes_zero_missing_and_unassigned_calls():
    env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[2] / "app/templates"), autoescape=select_autoescape())
    html = env.get_template("admin_quality.html").render(stats={
        "total_queries": 1, "token_usage": {"dropped_calls": 3},
        "llm_usage": [{"_id": {"provider": "fixture", "model": "m", "use_case": "answer"},
                       "calls": 2, "tokens": 4, "measured": 1,
                       "prompt_token_count": 0, "prompt_token_count_coverage": 1,
                       "output_token_count": 0, "output_token_count_coverage": 0,
                       "thinking_token_count": 4, "thinking_token_count_coverage": 1,
                       "total_token_count": 4, "total_token_count_coverage": 1}]})
    assert "3 lượt bị cắt" in html
    assert "không thể phân bổ" in html
    assert "Input" in html and "Thinking" in html
    assert 'data-token-field="prompt_token_count">0' in html
    assert 'data-token-field="output_token_count">N/A' in html
    assert 'data-token-field="thinking_token_count">4' in html
    assert "1/2" in html


def test_group_token_fields_use_the_request_integer_guard():
    from app.services.admin_observability import TOKEN_FIELDS, usage_facets, valid_token_integer
    group = next(stage["$group"] for stage in usage_facets()["llm_usage"] if "$group" in stage)
    for field in TOKEN_FIELDS:
        value = "$metrics.llm_calls." + field
        assert group[field]["$sum"]["$cond"] == [valid_token_integer(value), value, 0]
        assert group[field + "_coverage"]["$sum"]["$cond"] == [valid_token_integer(value), 1, 0]
