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
async def test_warm_guardrails_propagates_initialization_failure(
    monkeypatch,
) -> None:
    def fail():
        raise RuntimeError("guardrail unavailable")

    monkeypatch.setattr(guardrails, "get_rails", fail)

    with pytest.raises(RuntimeError, match="guardrail unavailable"):
        await guardrails.warm_guardrails()


@pytest.mark.asyncio
async def test_input_guardrail_failure_blocks_request(monkeypatch) -> None:
    monkeypatch.setattr(
        guardrails,
        "get_rails",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    safe, message = await guardrails.check_input_guardrails(
        "Điều kiện cấp phép là gì?"
    )

    assert safe is False
    assert message


@pytest.mark.asyncio
async def test_output_guardrail_timeout_blocks_response(monkeypatch) -> None:
    class SlowRails:
        async def generate_async(self, **_kwargs):
            raise TimeoutError("timeout")

    monkeypatch.setattr(guardrails, "get_rails", lambda: SlowRails())

    safe, message = await guardrails.check_output_guardrails(
        "Câu trả lời",
        ["Căn cứ pháp lý"],
        "Câu hỏi",
    )

    assert safe is False
    assert message


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
