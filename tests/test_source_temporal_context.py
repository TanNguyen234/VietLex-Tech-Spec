import pytest
from app.services.research_analysis import build_selected_evidence_prompt


def test_selected_source_keeps_reported_date_and_provenance_without_private_fields():
    evidence = {"evidence_id": "e1", "excerpt": "Nội dung", "reported_effective_from": "01-01-2027", "issued_date": "10-09-2026", "legal_effect_status": "unverified", "source_url": "https://vanban.chinhphu.vn/?docid=219442", "retrieved_at": "2026-09-13T00:00:00Z", "reviewer_private_email": "secret@example.test"}
    prompt = build_selected_evidence_prompt("Áp dụng tại 13/09/2026?", [evidence])
    assert "01-01-2027" in prompt
    assert "10-09-2026" in prompt
    assert evidence["source_url"] in prompt
    assert "unverified" in prompt
    assert evidence["retrieved_at"] in prompt
    assert "secret@example.test" not in prompt
    assert "không chứng nhận hiệu lực hiện hành" in prompt


def test_provenance_counts_toward_existing_context_budget():
    with pytest.raises(ValueError, match="evidence_scope_too_large"):
        build_selected_evidence_prompt("Q", [{"evidence_id": "e1", "excerpt": "X", "source_url": "x " * 721}])


@pytest.mark.asyncio
async def test_source_pin_and_snapshot_preserve_issued_date(monkeypatch):
    import inspect
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from app.api import trusted_source_routes as routes
    from app.api.workspace_routes import _evidence_snapshot
    source = {"url": "https://vanban.chinhphu.vn/?docid=219442", "title": "Public law", "text": "Public quote", "sha256": "abc", "retrieved_at": "2026-09-13T00:00:00Z", "issued_date": "10-09-2026"}
    workspace = {"analyses": [{"analysis_id": "a", "kind": "trusted_sources", "result": {"sources": [source]}}]}
    monkeypatch.setattr(routes, "_owned_workspace", AsyncMock(return_value=(workspace, "client", "user")))
    pin = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "pin_workspace_evidence", pin)
    await inspect.unwrap(routes.pin_source)(Request({"type": "http"}), "w", "a", 0, "Public quote", "csrf", None)
    evidence = pin.call_args.args[1]
    assert evidence["issued_date"] == source["issued_date"]
    assert _evidence_snapshot([evidence])[0]["issued_date"] == source["issued_date"]
