from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _RecoveryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.warnings: list[str] = []
        self._warning_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "p" and "legal-warning" in (values.get("class") or "").split():
            self._warning_depth += 1
            self.warnings.append("")
        if tag == "a" and values.get("href", "").startswith("/workspaces?"):
            self.links.append(values["href"])

    def handle_data(self, data: str) -> None:
        if self._warning_depth:
            self.warnings[-1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._warning_depth:
            self._warning_depth -= 1


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr('app.api.routes.check_input_guardrails', AsyncMock(return_value=(True, '')))
    monkeypatch.setattr('app.api.routes.check_output_guardrails', AsyncMock(return_value=(True, '')))
    from app.api.dependencies import verify_csrf
    from app.api.routes import router

    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[verify_csrf] = lambda: "valid"
    app.include_router(router)
    return TestClient(app)


def _recovery(html: str) -> tuple[str, str]:
    parser = _RecoveryParser()
    parser.feed(html)
    assert len(parser.links) == 1
    assert len(parser.warnings) == 1
    return parser.warnings[0].strip(), parser.links[0]


def test_live_and_history_share_escaped_no_evidence_recovery(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.routes as routes

    query = 'Câu hỏi <img src=x onerror="alert(1)"> & "phạm vi"'
    monkeypatch.setattr(routes.settings, "PUBLIC_NEMO_DEFAULT_ENABLED", False)
    monkeypatch.setattr(routes, "check_semantic_cache", AsyncMock(return_value=None))
    monkeypatch.setattr(
        routes,
        "run_advanced_rag",
        AsyncMock(return_value=("Chưa có căn cứ.", [], {"t_total": 0.1})),
    )
    monkeypatch.setattr(routes, "log_interaction", AsyncMock())
    monkeypatch.setattr(routes, "save_to_semantic_cache", AsyncMock())

    live = client.post(
        "/chat",
        data={"message": query, "csrf_token": "valid", "session_id": "s-1"},
    )
    assert live.status_code == 200

    monkeypatch.setattr(
        routes,
        "get_session_messages",
        AsyncMock(
            return_value=[
                {
                    "user_query": query,
                    "bot_response": "Chưa có căn cứ.",
                    "trace_id": "trace-1",
                    "contexts": [],
                    "cached": False,
                    "feedback": None,
                }
            ]
        ),
    )
    history = client.get("/sessions/s-1")
    assert history.status_code == 200

    live_warning, live_href = _recovery(live.text)
    history_warning, history_href = _recovery(history.text)
    assert history_warning == live_warning
    assert history_href == live_href
    assert parse_qs(urlsplit(live_href).query)["question"] == [query]
    assert "<img src=x" not in live_href
    assert "<img src=x" not in history_href


def test_drawer_is_inert_initially_and_brand_name_uses_visible_text() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    index = (root / "app/templates/index.html").read_text(encoding="utf-8")
    nav = (root / "app/templates/product_nav.html").read_text(encoding="utf-8")

    assert '<aside id="evidence-drawer"' in index
    assert 'aria-hidden="true" inert' in index or 'inert aria-hidden="true"' in index
    for template in (index, nav):
        assert 'class="brand-mark" aria-hidden="true">VL' in template
        brand = re.search(r'<a class="brand[^"]*" href="/"[^>]*>', template)
        assert brand is not None
        assert "aria-label=" not in brand.group(0)


@pytest.mark.asyncio
async def test_request_only_official_context_is_still_filtered_from_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.database as database
    from app.services.evidence_presenter import EphemeralOfficialEvidenceContext

    monkeypatch.setattr(database.settings, "APP_ENV", "development")
    stored = await database.log_interaction(
        trace_id="trace-ephemeral",
        user_query="Câu hỏi",
        bot_response="Câu trả lời",
        contexts=["Corpus evidence", EphemeralOfficialEvidenceContext("PRIVATE REQUEST BODY")],
        cached=False,
    )

    assert stored["contexts"] == ["Corpus evidence"]
    assert "PRIVATE REQUEST BODY" not in str(stored)
