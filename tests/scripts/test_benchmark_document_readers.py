import json
import socket
from pathlib import Path

import pytest

import scripts.benchmark_document_readers as benchmark


def test_current_html_backend_measures_real_reader_offline_and_preserves_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    network_methods = [
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ]
    network_methods.extend(
        (socket.socket, name)
        for name in ("sendto", "sendmsg")
        if hasattr(socket.socket, name)
    )
    for owner, name in network_methods:
        monkeypatch.setattr(owner, name, getattr(owner, name))

    source_fixture = Path("benchmark_fixtures/document_readers/official_page.html")
    html_path = tmp_path / source_fixture.name
    html_path.write_bytes(source_fixture.read_bytes())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "purpose": "synthetic HTML reader baseline test",
                "fixtures": [
                    {
                        "id": "synthetic-official-page",
                        "path": html_path.name,
                        "kind": "html",
                        "expected_numbers": ["12/2026/NĐ-CP"],
                        "expected_articles": ["Điều 5"],
                        "expected_clauses": ["1. Cơ quan có thẩm quyền"],
                        "expected_dates": ["09-09-2026"],
                        "expected_quotes": ["Cơ quan có thẩm quyền tiếp nhận hồ sơ"],
                        "limitations": ["Fixed synthetic fixture only"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)

    result = benchmark.run_benchmark(manifest_path, "current-html", repeats=1)

    extraction = result["results"][0]["extractors"]["current_html"]
    assert extraction["status"] == "OK", extraction
    assert extraction["reader"] == "app.services.trusted_source_reader.extract_page"
    assert len(extraction["reader_source_sha256"]) == 64
    assert extraction["fixture_source_sha256"] == result["results"][0]["input_sha256"]
    assert extraction["preservation"]["numbers"]["status"] == "PASS"
    assert extraction["preservation"]["articles"]["status"] == "PASS"
    assert extraction["preservation"]["clauses"]["status"] == "PASS"
    assert extraction["preservation"]["dates"]["status"] == "PASS"
    assert extraction["preservation"]["quotes"]["status"] == "PASS"
    assert extraction["process_peak_rss_mib"] is not None
    network = result["execution"]["network"]
    assert network["status"] == "SOCKET_API_GUARDED"
    assert {
        "socket.socket.connect",
        "socket.socket.connect_ex",
        "socket.socket.sendto",
        "socket.create_connection",
        "socket.getaddrinfo",
    } <= set(network["blocked_entrypoints"])
    if hasattr(socket.socket, "sendmsg"):
        assert "socket.socket.sendmsg" in network["blocked_entrypoints"]
    assert "not a process-wide or OS-level network sandbox" in network["scope"]

    with pytest.raises(RuntimeError, match="benchmark_network_disabled"):
        socket.create_connection(("example.invalid", 443))
    for name in ("sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            with pytest.raises(RuntimeError, match="benchmark_network_disabled"):
                getattr(socket.socket, name)(None, [b""] if name == "sendmsg" else b"", ("127.0.0.1", 9))


def test_markitdown_pdf_backend_never_constructs_generic_wrapper_or_magika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    network_methods = [
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
    ]
    network_methods.extend(
        (socket.socket, name)
        for name in ("sendto", "sendmsg")
        if hasattr(socket.socket, name)
    )
    for owner, name in network_methods:
        monkeypatch.setattr(owner, name, getattr(owner, name))
    benchmark._disable_network()

    pytest.importorskip("markitdown")

    source_pdf = Path("docs/verification/ocr-output-20260913/aviation-first-page.pdf")
    pdf_path = tmp_path / source_pdf.name
    pdf_path.write_bytes(source_pdf.read_bytes())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "purpose": "direct PDF converter model-call regression",
                "fixtures": [
                    {
                        "id": "single-page-pdf",
                        "path": pdf_path.name,
                        "kind": "pdf",
                        "selected_pages": [1],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)

    result = benchmark.run_benchmark(manifest_path, "markitdown", repeats=1)

    extraction = result["results"][0]["extractors"]["markitdown_pdf"]
    assert extraction["status"] == "OK", extraction
    tripwire = result["execution"]["model_inference_tripwire"]
    assert tripwire["status"] == "PASS", tripwire
    assert tripwire["completed_measurements"] == 1
    assert result["schema_version"] == "document-readers-benchmark-v4"
    assert extraction["reader"] == "markitdown.converters.PdfConverter"
    assert extraction["cold_ms"]["samples"] == 1
    assert extraction["warm_ms"]["samples"] == 1
    assert result["benchmark_script"]["sha256"] == benchmark.sha256(
        Path(benchmark.__file__).resolve().read_bytes()
    ).hexdigest()

    def fail_measurement(*_args, **_kwargs):
        raise RuntimeError("synthetic_pdf_measurement_failure")

    monkeypatch.setattr(benchmark, "_measure", fail_measurement)
    failed = benchmark.run_benchmark(manifest_path, "markitdown", repeats=1)
    assert failed["results"][0]["extractors"]["markitdown_pdf"]["status"] == "ERROR"
    failed_tripwire = failed["execution"]["model_inference_tripwire"]
    assert failed_tripwire["status"] == "INCOMPLETE", failed_tripwire
    assert failed_tripwire["completed_measurements"] == 0
    assert failed_tripwire["failed_fixtures"] == ["single-page-pdf"]
    assert tripwire["attempts"] == {
        "markitdown_constructor": 0,
        "markitdown_convert_stream": 0,
        "magika_constructor": 0,
        "magika_identify_stream": 0,
    }
