from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.vertex_ai import VertexQuotaError
from scripts import probe_natural_rag as probe


def test_live_execution_requires_explicit_opt_in(monkeypatch, tmp_path: Path) -> None:
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("live runner must not be invoked")

    monkeypatch.setattr(probe, "run_live_probe", fail_if_called)
    with pytest.raises(SystemExit) as exc_info:
        probe.main(["--output-root", str(tmp_path)])

    assert exc_info.value.code == 2
    assert called is False
    assert list(tmp_path.iterdir()) == []


def test_request_cap_counts_failed_vertex_http_attempts_and_blocks_next(
    tmp_path: Path,
) -> None:
    class FailingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(503, request=request, text="temporary")

    async def exercise() -> None:
        ledger_path = tmp_path / "attempt_ledger.json"
        ledger = probe.VertexRequestLedger(ledger_path, max_requests=2)
        inner = FailingTransport()
        transport = probe.VertexAttemptTransport(ledger, inner)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(3):
                try:
                    await client.post(
                        "https://us-central1-aiplatform.googleapis.com/v1/"
                        "projects/private-project/locations/us-central1/"
                        "publishers/google/models/gemini-3.5-flash:generateContent",
                        headers={"Authorization": "Bearer must-not-be-saved"},
                        json={"contents": [{"text": "private prompt"}]},
                    )
                except probe.VertexRequestCapExceeded:
                    pass

        saved = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert inner.calls == 2
        assert saved["actual_vertex_requests"] == 2
        assert [item["http_status"] for item in saved["attempts"]] == [503, 503]
        assert saved["blocked_attempts"] == 1
        serialized = ledger_path.read_text(encoding="utf-8")
        assert "private-project" not in serialized
        assert "must-not-be-saved" not in serialized
        assert "private prompt" not in serialized

    asyncio.run(exercise())


def test_vertex_only_generation_disables_fallback_and_retries() -> None:
    observed: dict[str, object] = {}

    async def call(*args, **kwargs):
        observed.update(kwargs)
        return "generated"

    wrapped = probe.vertex_only_generation(call)
    assert asyncio.run(wrapped("safe test prompt")) == "generated"
    assert observed["allow_fallback"] is False
    assert observed["max_retries"] == 0


def test_runtime_overrides_match_serverless_vertex_lane_without_changing_selector() -> None:
    settings = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        SERVERLESS_ONLINE_ONLY=False,
        VERTEX_MAX_RETRIES=2,
        RAGAS_EVALUATION_MODE="all",
    )

    with probe.serverless_probe_settings(settings):
        assert settings.USE_LEGACY_FREE_PIPELINE is False
        assert settings.SERVERLESS_ONLINE_ONLY is True
        assert settings.VERTEX_MAX_RETRIES == 0
        assert settings.RAGAS_EVALUATION_MODE == "off"

    assert settings.SERVERLESS_ONLINE_ONLY is False
    assert settings.VERTEX_MAX_RETRIES == 2
    assert settings.RAGAS_EVALUATION_MODE == "all"


def test_legacy_selector_is_rejected_instead_of_cross_fallback() -> None:
    settings = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=True,
        SERVERLESS_ONLINE_ONLY=False,
        VERTEX_MAX_RETRIES=2,
        RAGAS_EVALUATION_MODE="off",
    )

    with pytest.raises(probe.ProbePreflightError, match="legacy pipeline"):
        with probe.serverless_probe_settings(settings):
            pass


def test_artifact_redaction_removes_secrets_and_url_query_strings() -> None:
    safe = probe.sanitize_artifact_data(
        {
            "authorization": "Bearer private-token",
            "answer": "Bearer private-token from C:\\secret\\service.json",
            "source_url": "https://example.gov.vn/law?id=private-token",
            "api_key": "private-key",
        }
    )

    serialized = json.dumps(safe, ensure_ascii=False)
    assert "private-token" not in serialized
    assert "private-key" not in serialized
    assert "service.json" not in serialized
    assert "?" not in safe["source_url"]


def test_probe_cases_are_fixed_ordinary_questions_without_legal_numbers() -> None:
    cases = probe.probe_cases()

    assert [case.case_id for case in cases] == [
        "rental_deposit",
        "probationary_work",
        "environmental_permit",
    ]
    assert len(cases) == 3
    assert all(not any(char.isdigit() for char in case.question) for case in cases)
    assert "thử việc" in cases[1].question.casefold()
    assert "trả lương" in cases[1].question.casefold()
    assert "nhập khẩu phế liệu" in cases[2].question.casefold()
    assert "hiện nay" in cases[2].question.casefold()
    assert "giấy phép môi trường" in cases[2].question.casefold()


@pytest.mark.parametrize("failure", ["401", "403", "429", "503", "transport"])
def test_case_loop_stops_after_wrapped_vertex_http_failure(
    failure: str,
    tmp_path: Path,
) -> None:
    class FailureTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if failure == "transport":
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(int(failure), request=request, text="provider error")

    async def exercise() -> None:
        ledger = probe.VertexRequestLedger(
            tmp_path / f"ledger-{failure}.json",
            max_requests=6,
        )
        transport = probe.VertexAttemptTransport(ledger, FailureTransport())
        client = httpx.AsyncClient(transport=transport)
        calls = 0

        async def wrapped_pipeline(_case):
            nonlocal calls
            calls += 1
            try:
                response = await client.post(
                    "https://us-central1-aiplatform.googleapis.com/v1/"
                    "projects/test-project/locations/us-central1/"
                    "publishers/google/models/gemini-3.5-flash:generateContent"
                )
                status = "quota" if response.status_code == 429 else "provider_error"
            except httpx.RequestError:
                status = "network"
            # The application pipeline can turn the provider failure into a
            # normal return value, so stopping must also inspect the ledger.
            return "technical response", [], {
                "generation_status": status,
                "provider_usage": {
                    "answer_generation": {
                        "provider": "google_vertex_ai",
                        "status": status,
                        "primary_error_kind": status,
                        "observed": True,
                    }
                },
            }

        try:
            results, stop_reason = await probe._run_probe_cases(
                wrapped_pipeline,
                ledger,
                max_requests=6,
            )
        finally:
            await client.aclose()

        assert calls == 1
        assert len(results) == 1
        assert stop_reason == "vertex_provider_error"

    asyncio.run(exercise())


def test_case_loop_stops_on_typed_vertex_error_even_without_recorded_http_attempt(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        ledger = probe.VertexRequestLedger(
            tmp_path / "typed-ledger.json",
            max_requests=6,
        )
        calls = 0

        async def typed_failure(_case):
            nonlocal calls
            calls += 1
            raise VertexQuotaError("quota exhausted", status_code=429)

        results, stop_reason = await probe._run_probe_cases(
            typed_failure,
            ledger,
            max_requests=6,
        )

        assert calls == 1
        assert len(results) == 1
        assert stop_reason == "vertex_provider_error"

    asyncio.run(exercise())


def test_case_loop_propagates_cancellation_without_starting_another_case(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        ledger = probe.VertexRequestLedger(
            tmp_path / "cancel-ledger.json",
            max_requests=6,
        )
        calls = 0

        async def cancelled(_case):
            nonlocal calls
            calls += 1
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await probe._run_probe_cases(cancelled, ledger, max_requests=6)
        assert calls == 1

    asyncio.run(exercise())


def test_case_loop_stops_after_pre_http_retrieval_pipeline_error(
    tmp_path: Path,
) -> None:
    from app.services.runtime_errors import RetrievalPipelineError

    async def exercise() -> None:
        ledger = probe.VertexRequestLedger(
            tmp_path / "retrieval-error-ledger.json",
            max_requests=6,
        )
        calls = 0

        async def retrieval_failure(_case):
            nonlocal calls
            calls += 1
            error = RetrievalPipelineError(
                "retrieval_error",
                "retrieval failed before a Vertex request",
                {},
                {"retrieval_status": "retrieval_error"},
            )
            raise error

        results, stop_reason = await probe._run_probe_cases(
            retrieval_failure,
            ledger,
            max_requests=6,
        )

        assert calls == 1
        assert len(results) == 1
        assert stop_reason == "retrieval_pipeline_error"
        assert ledger.actual_vertex_requests == 0

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("artifact_status", "expected_exit"),
    [
        ("completed", 0),
        ("preflight_failed", 1),
        ("failed_before_first_case", 1),
        ("stopped", 1),
    ],
)
def test_cli_exit_status_reports_noncompleted_run(
    monkeypatch,
    tmp_path: Path,
    artifact_status: str,
    expected_exit: int,
) -> None:
    run_dir = tmp_path / artifact_status
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": artifact_status,
                "evidence_level": "NOT RUN" if artifact_status != "completed" else "live",
                "actual_vertex_requests": 0,
                "max_vertex_requests": 6,
            }
        ),
        encoding="utf-8",
    )

    async def completed(_args):
        return run_dir

    monkeypatch.setattr(probe, "run_live_probe", completed)

    assert probe.main(["--allow-live", "--output-root", str(tmp_path)]) == expected_exit


def test_adc_presence_includes_dotenv_boundary_without_saving_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    (tmp_path / ".env").write_text(
        "GOOGLE_APPLICATION_CREDENTIALS=private-service-account.json\n",
        encoding="utf-8",
    )

    presence = probe._credential_presence(SimpleNamespace(GOOGLE_CLOUD_PROJECT="test"))

    assert presence["adc_dotenv_path_present"] is True
    assert "private-service-account.json" not in json.dumps(presence)


def test_live_provenance_requires_usable_dirty_tree_hashes() -> None:
    assert not probe._live_provenance_is_usable(
        {"status": "unavailable", "git_dirty": False}
    )
    assert not probe._live_provenance_is_usable(
        {
            "status": "ok",
            "git_dirty": True,
            "git_diff_sha256": None,
            "source_state_sha256": "b" * 64,
        }
    )
    assert not probe._live_provenance_is_usable(
        {
            "status": "ok",
            "git_dirty": True,
            "git_diff_sha256": "a" * 64,
            "source_state_sha256": None,
        }
    )
    assert probe._live_provenance_is_usable(
        {
            "status": "ok",
            "git_dirty": True,
            "git_diff_sha256": "a" * 64,
            "source_state_sha256": "b" * 64,
        }
    )

