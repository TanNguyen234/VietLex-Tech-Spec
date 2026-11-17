import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import official_instrument_hypotheses as hyp
from app.services.official_instrument_hypotheses import (
    InstrumentHypotheses,
    explicit_inputs_from_hypotheses,
    hypothesis_gaps,
    hypothesis_queries,
    parse_hypotheses,
    propose_instrument_hypotheses,
)


def _settings(**overrides):
    values = {
        "CHAT_INSTRUMENT_HYPOTHESIS_ENABLED": True,
        "CHAT_INSTRUMENT_HYPOTHESIS_TIMEOUT_SECONDS": 5.0,
        "CHAT_INSTRUMENT_HYPOTHESIS_MAX_OUTPUT_TOKENS": 768,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(status="success", text="{}"):
    return SimpleNamespace(
        status=status,
        text=text,
        observed_provider="google_vertex_ai",
        observed_model="gemini-test",
        finish_reason="STOP",
        output_token_count=120,
    )


def test_parse_keeps_valid_items_and_drops_malformed():
    text = json.dumps(
        {
            "instruments": [
                {"title": "Luật Bảo hiểm xã hội", "number": "41/2024/QH15", "year": 2024},
                {"title": "x", "number": None, "year": None},
                {"title": "Nghị định xử phạt giao thông", "number": "bad number", "year": True},
                "not-a-dict",
            ],
            "legal_points": ["đóng bảo hiểm xã hội bắt buộc", "một", "điểm pháp lý rất dài " * 10],
        },
        ensure_ascii=False,
    )
    instruments, points = parse_hypotheses(text)
    assert instruments == (
        ("Luật Bảo hiểm xã hội", "41/2024/QH15", 2024),
        ("Nghị định xử phạt giao thông", None, None),
    )
    assert points == ("đóng bảo hiểm xã hội bắt buộc",)


def test_parse_rejects_non_object_shape():
    with pytest.raises(ValueError):
        parse_hypotheses("[]")


def test_queries_prefer_number_then_year_then_title():
    hypotheses = InstrumentHypotheses(
        "ok",
        (
            ("Luật Bảo hiểm xã hội", "41/2024/QH15", 2024),
            ("Nghị định lương tối thiểu vùng", None, 2025),
            ("Thông tư hướng dẫn", None, None),
        ),
        ("đóng bảo hiểm xã hội bắt buộc",),
    )
    assert hypothesis_queries(hypotheses) == (
        "Luật Bảo hiểm xã hội 41/2024/QH15",
        "Nghị định lương tối thiểu vùng 2025",
        "Thông tư hướng dẫn",
    )


def test_gaps_report_uncovered_point_when_number_is_present():
    hypotheses = InstrumentHypotheses(
        "ok",
        (("Nghị định xử phạt giao thông đường bộ", "168/2024/NĐ-CP", 2024),),
        ("tạm giữ phương tiện", "tước quyền sử dụng giấy phép lái xe"),
    )
    contexts = [
        "[Nguồn chính thức ngoài VietLex · 168/2024/NĐ-CP]\n"
        "Số hiệu: 168/2024/NĐ-CP\n"
        "Nội dung: tước quyền sử dụng giấy phép lái xe trong 22 tháng."
    ]
    assert hypothesis_gaps(hypotheses, contexts) == (False, ("tạm giữ phương tiện",))


def test_gaps_report_absent_numbered_instrument():
    hypotheses = InstrumentHypotheses("ok", (("Luật Bảo hiểm xã hội", "41/2024/QH15", 2024),), ())
    contexts = ["[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\nSố hiệu: 45/2019/QH14\nNội dung: hợp đồng"]
    assert hypothesis_gaps(hypotheses, contexts) == (True, ())


def test_gaps_empty_when_hypotheses_not_ok():
    assert hypothesis_gaps(InstrumentHypotheses("timeout"), ["x"]) == (False, ())


def test_explicit_inputs_merge_registry_and_hypotheses_without_duplicates():
    hypotheses = InstrumentHypotheses(
        "ok", (("Luật Bảo hiểm xã hội", "41/2024/QH15", 2024),), ("đóng bảo hiểm xã hội",)
    )
    queries, topics, hint = explicit_inputs_from_hypotheses(
        hypotheses,
        base_queries=("Luật Bảo hiểm xã hội 41/2024/QH15", "Luật Bảo hiểm xã hội 2024 hưởng lương hưu"),
        base_topics=("bao hiem xa hoi",),
        base_hint="điều kiện hưởng lương hưu",
    )
    assert queries == ("Luật Bảo hiểm xã hội 41/2024/QH15", "Luật Bảo hiểm xã hội 2024 hưởng lương hưu")
    assert topics == ("bao hiem xa hoi", "dong bao hiem xa hoi")
    assert hint == "điều kiện hưởng lương hưu; đóng bảo hiểm xã hội"


def test_propose_disabled_makes_no_model_call(monkeypatch):
    calls = []

    async def fake(prompt, system_prompt, *, max_output_tokens):
        calls.append(prompt)
        return _result()

    monkeypatch.setattr(hyp, "_generate", fake)
    result = asyncio.run(
        propose_instrument_hypotheses("q", settings=_settings(CHAT_INSTRUMENT_HYPOTHESIS_ENABLED=False))
    )
    assert result.status == "disabled"
    assert calls == []


def test_propose_success_parses_model_json(monkeypatch):
    payload = json.dumps(
        {
            "instruments": [{"title": "Luật Bảo hiểm xã hội", "number": "41/2024/QH15", "year": 2024}],
            "legal_points": ["đóng bảo hiểm xã hội bắt buộc"],
        },
        ensure_ascii=False,
    )

    async def fake(prompt, system_prompt, *, max_output_tokens):
        assert max_output_tokens == 768
        return _result(text=payload)

    monkeypatch.setattr(hyp, "_generate", fake)
    result = asyncio.run(propose_instrument_hypotheses("q", settings=_settings()))
    assert result.status == "ok"
    assert result.instruments == (("Luật Bảo hiểm xã hội", "41/2024/QH15", 2024),)
    assert result.diagnostics["model"] == "gemini-test"


def test_propose_timeout_and_provider_error_never_raise(monkeypatch):
    async def slow(prompt, system_prompt, *, max_output_tokens):
        await asyncio.sleep(1.0)
        return _result()

    monkeypatch.setattr(hyp, "_generate", slow)
    timed_out = asyncio.run(
        propose_instrument_hypotheses("q", settings=_settings(CHAT_INSTRUMENT_HYPOTHESIS_TIMEOUT_SECONDS=0.05))
    )
    assert timed_out.status == "timeout"

    async def failing(prompt, system_prompt, *, max_output_tokens):
        return _result(status="error")

    monkeypatch.setattr(hyp, "_generate", failing)
    errored = asyncio.run(propose_instrument_hypotheses("q", settings=_settings()))
    assert errored.status == "provider_error"


def test_propose_invalid_output_is_not_ok(monkeypatch):
    async def fake(prompt, system_prompt, *, max_output_tokens):
        return _result(text="không phải json")

    monkeypatch.setattr(hyp, "_generate", fake)
    result = asyncio.run(propose_instrument_hypotheses("q", settings=_settings()))
    assert result.status == "invalid_output"
    assert result.instruments == ()
