from types import SimpleNamespace

import pytest

from app.services import guardrails


@pytest.mark.asyncio
async def test_warm_guardrails_initializes_rails_once(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        guardrails,
        "get_rails",
        lambda: calls.append("get_rails") or object(),
    )

    await guardrails.warm_guardrails()

    assert calls == ["get_rails"]


@pytest.mark.asyncio
async def test_output_block_audit_logs_hash_not_raw_answer(
    monkeypatch,
) -> None:
    class FakeRails:
        async def generate_async(self, **_kwargs):
            return SimpleNamespace(
                response=[
                    {"content": "I'm sorry, I can't respond to that."}
                ]
            )

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(guardrails, "get_rails", lambda: FakeRails())
    monkeypatch.setattr(
        guardrails.logfire,
        "warning",
        lambda message, **fields: logged.append((message, fields)),
    )

    safe, _ = await guardrails.check_output_guardrails(
        "nội dung không được công bố",
        ["[72/2020/QH14, Điều 1] căn cứ"],
        "câu hỏi",
    )

    assert safe is False
    assert len(logged[0][1]["response_sha256"]) == 64
    assert "nội dung không được công bố" not in str(logged)
