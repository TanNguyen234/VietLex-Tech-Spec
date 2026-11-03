from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.evidence_presenter import (
    EphemeralOfficialEvidenceContext,
    TrustedOfficialEvidenceContext,
    evidence_context_provenance,
    present_context,
    restore_evidence_contexts,
)


def official_context(*, body="Điều 1. Quy định công khai."):
    return EphemeralOfficialEvidenceContext(
        "[Nguồn chính thức ngoài VietLex · 45/2019/QH14]\n"
        "Nguồn: https://vanban.chinhphu.vn/default.aspx?docid=123\n"
        "Nguồn loại: official_external\n"
        "Hiệu lực pháp lý: unverified\n"
        f"SHA-256 nguồn: {'a' * 64}\n"
        "Thời điểm đọc: 2026-10-15T10:00:00+00:00\n"
        "Phương thức đọc: visible_html_text\n"
        "Tiêu đề: Bộ luật Lao động\n" + body
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [{"client_id": "owner-a"}, {"user_id": "user-a"}])
async def test_public_snapshot_survives_owner_replay_and_export(monkeypatch, owner):
    import app.database as database
    from app.services.conversation_export import render_conversation_markdown
    from app.services.semantic_cache import _contains_official_external_context

    monkeypatch.setattr(database.settings, "APP_ENV", "production")
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock()
    logs = MagicMock(replace_one=AsyncMock(), find_one=AsyncMock())
    logs.find.return_value = cursor
    monkeypatch.setattr(database, "get_db", lambda: SimpleNamespace(evaluation_logs=logs))
    official = official_context()
    contexts = ["Corpus first", official, "Corpus last", official_context(body="Điều 2. Công khai.")]
    saved = await database.log_interaction("trace-public", "question", "answer", contexts,
                                           False, session_id="session-public", **owner)
    assert saved["contexts"] == contexts
    assert saved["expires_at"] - saved["timestamp"] == timedelta(days=database.settings.DATA_RETENTION_DAYS)
    logs.find_one.return_value = deepcopy(saved)
    cursor.to_list.return_value = [deepcopy(saved)]
    owned = await database.get_owned_interaction("trace-public", "owner-a", user_id=owner.get("user_id"))
    messages = await database.get_session_messages("session-public", "owner-a", user_id=owner.get("user_id"))
    assert logs.find_one.call_args.args[0] == {"_id": "trace-public", **owner}
    assert logs.find.call_args.args[0] == {"session_id": "session-public", **owner}
    for restored in (owned["contexts"], messages[0]["contexts"]):
        assert restored == contexts
        assert isinstance(restored[1], EphemeralOfficialEvidenceContext)
        view = present_context(restored[1])
        assert view.source_sha256 == "a" * 64
        assert view.legal_effect_status == "unverified"
        assert view.source_url == "https://vanban.chinhphu.vn/default.aspx?docid=123"
        assert _contains_official_external_context(restored)
    markdown = render_conversation_markdown({"title": "Conversation"}, messages)
    assert markdown.index("Corpus first") < markdown.index(str(official).splitlines()[0]) < markdown.index("Corpus last")
    assert "SHA-256 nguồn: " + "a" * 64 in markdown
    assert "Điều 2. Công khai." in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize("change,reason", [
    (lambda text: text.replace("vanban.chinhphu.vn", "evil.example"), "invalid_official_provenance"),
    (lambda text: text.replace("unverified", "verified"), "invalid_official_provenance"),
    (lambda text: text.replace("a" * 64, "bad-hash"), "invalid_official_provenance"),
    (lambda text: text + " x" * 8000, "public_snapshot_budget_exceeded"),
    (lambda text: text + "x" * 256001, "public_snapshot_budget_exceeded"),
])
async def test_rejected_snapshot_is_observable_without_retaining_body(monkeypatch, change, reason):
    import app.database as database
    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    invalid = EphemeralOfficialEvidenceContext(change(str(official_context())))
    saved = await database.log_interaction("trace-invalid", "question", "answer", ["Corpus", invalid],
                                           False, client_id="owner-a")
    assert saved["contexts"] == ["Corpus"]
    assert saved["metrics"]["evidence_persistence"]["excluded_contexts"] == [{"index": 1, "reason": reason}]
    assert str(invalid) not in str(saved)


@pytest.mark.asyncio
async def test_public_snapshot_requires_owner_and_caps_count(monkeypatch):
    import app.database as database
    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    contexts = [official_context()] * 17
    unowned = await database.log_interaction("unowned", "q", "a", contexts[:1], False)
    assert unowned["contexts"] == []
    assert unowned["metrics"]["evidence_persistence"]["excluded_contexts"] == [{"index": 0, "reason": "snapshot_owner_required"}]
    saved = await database.log_interaction("bounded", "q", "a", contexts, False, client_id="owner-a")
    assert len(saved["contexts"]) == 16
    assert saved["metrics"]["context_count"] == 17
    assert saved["metrics"]["evidence_persistence"]["excluded_contexts"] == [{"index": 16, "reason": "public_snapshot_budget_exceeded"}]


def test_snapshot_provenance_cannot_be_rebound_to_modified_text():
    context = official_context()
    sidecar = evidence_context_provenance(context)
    altered = str(context).replace("Quy định công khai", "Forged legal rule")
    restored = restore_evidence_contexts([altered], [sidecar])
    assert not isinstance(restored[0], TrustedOfficialEvidenceContext)
    assert present_context(restored[0]).source_type is None


@pytest.mark.asyncio
async def test_log_keeps_explicit_unknown_guardrail_state(monkeypatch):
    import app.database as database
    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    state = {"mode": "off", "requested": False, "executed": False, "status": "not_run",
             "input_safe": None, "output_safe": None, "stages": {}}
    saved = await database.log_interaction("off", "q", "a", [], False,
                                           input_safe=None, output_safe=None, guardrail_state=state)
    assert saved["guardrail_state"] == state
    assert saved["safety_status"]["input_safe"] is None
    assert saved["safety_status"]["output_safe"] is None


@pytest.mark.asyncio
async def test_rehydrated_public_snapshot_cannot_enter_shared_cache(monkeypatch):
    from app.services import semantic_cache
    context = official_context()
    restored = restore_evidence_contexts([str(context)], [evidence_context_provenance(context)])
    embed = MagicMock(side_effect=AssertionError("cache embedding must not run"))
    monkeypatch.setattr(semantic_cache, "embed_query", embed)
    await semantic_cache.save_to_semantic_cache("Câu hỏi về hợp đồng", "Câu trả lời", restored)
    embed.assert_not_called()


def test_public_pdf_snapshot_preserves_reader_provenance():
    text = str(official_context()).replace("Tiêu đề:", (
        f"SHA-256 tệp PDF: {'b' * 64}\n"
        "Tệp PDF: https://datafiles.chinhphu.vn/law.pdf\n"
        "Phạm vi trang PDF: 1-5/12\n"
        "Đọc một phần PDF: có\nTiêu đề:"
    ))
    context = EphemeralOfficialEvidenceContext(text)
    restored = restore_evidence_contexts([text], [evidence_context_provenance(context)])[0]
    assert isinstance(restored, EphemeralOfficialEvidenceContext)
    assert present_context(restored) == present_context(context)
    assert present_context(restored).document_sha256 == "b" * 64


def test_malformed_snapshot_marker_does_not_break_history():
    context = official_context()
    sidecar = {**evidence_context_provenance(context), "kind": ["forged"]}
    restored = restore_evidence_contexts([str(context)], [sidecar])
    assert type(restored[0]) is str
