"""Offline parser comparison on fixed, manifest-selected local fixtures.

No source selection is implemented here: every PDF backend receives the same
bounded PDF bytes, and the manifest records their physical page numbers.
"""

from __future__ import annotations

import argparse
import ctypes
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module, metadata
from io import BytesIO
import json
import math
import platform
import re
import socket
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmark_fixtures" / "document_readers" / "manifest.json"
CURRENT_HTML_TEST_URL = "https://vanban.chinhphu.vn/benchmark-fixture"
PDF_MAX_BYTES = 20_000_000
PDF_MAX_PAGES = 200
PDF_MAX_RETAINED = 5
PAGE_TEXT_LIMIT = 20_000
TEXT_LIMIT = 20_000


def _disable_network():
    def denied(*_args, **_kwargs):
        raise RuntimeError("benchmark_network_disabled")

    blocked = []
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, denied)
            blocked.append(f"socket.socket.{name}")
    for name in ("create_connection", "getaddrinfo"):
        setattr(socket, name, denied)
        blocked.append(f"socket.{name}")
    return blocked


def _fold(value: str) -> str:
    value = str(value or "").casefold().replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    plain = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", plain).strip()


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _timing(cold: list[float], warm: list[float]) -> dict:
    return {
        "cold_ms": {
            "samples": len(cold),
            "p50": _percentile(cold, 0.50),
            "p95": _percentile(cold, 0.95),
        },
        "warm_ms": {
            "samples": len(warm),
            "p50": _percentile(warm, 0.50),
            "p95": _percentile(warm, 0.95),
        },
        "definition": (
            "Cold records calls before the warm-up; warm records calls after one "
            "unrecorded warm-up. Backend-specific object reuse is preserved. "
            "Imports and process startup are excluded."
        ),
    }


def _peak_working_set() -> tuple[float | None, str]:
    """Read process high-water RSS without requiring an optional package."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            psapi = ctypes.WinDLL("Psapi.dll")
            kernel32 = ctypes.WinDLL("kernel32.dll")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            ok = psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                mib = counters.PeakWorkingSetSize / (1024 * 1024)
                return round(mib, 2), "process_peak_working_set_high_water_shared_across_benchmarks"
        except Exception:
            pass
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mib = value / (1024 * 1024) if sys.platform != "darwin" else value / 1024
        return round(mib, 2), "process_peak_rss_high_water_shared_across_benchmarks"
    except Exception:
        return None, "NOT MEASURED (platform API unavailable)"


def _distribution(name: str) -> dict:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return {"installed": False, "version": None, "files_bytes": None}
    total = 0
    complete = True
    for relative in dist.files or ():
        try:
            path = Path(dist.locate_file(relative))
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            complete = False
    return {
        "installed": True,
        "version": dist.version,
        "files_bytes": total if complete else None,
    }


def _prepare_selected_pdf(payload: bytes, fixture: dict) -> dict:
    """Create one bounded physical-page slice for all PDF parser backends."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError

    if len(payload) > PDF_MAX_BYTES or not payload.startswith(b"%PDF-"):
        raise ValueError("fixture_pdf_invalid_or_too_large")
    selected = fixture.get("selected_pages")
    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) > PDF_MAX_RETAINED
        or any(
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            for number in selected
        )
        or selected != list(range(selected[0], selected[-1] + 1))
    ):
        raise ValueError("manifest_selected_pages_invalid")
    try:
        try:
            reader = PdfReader(BytesIO(payload), strict=True)
            recovered = False
        except PdfReadError:
            reader = PdfReader(BytesIO(payload), strict=False)
            recovered = True
        if reader.is_encrypted:
            raise ValueError("fixture_pdf_encrypted")
        count = len(reader.pages)
        if not 1 <= count <= PDF_MAX_PAGES or selected[-1] > count:
            raise ValueError("fixture_pdf_page_limit_or_selection_invalid")
        writer = PdfWriter()
        observed_pages = []
        for physical in selected:
            page = reader.pages[physical - 1]
            text = page.extract_text() or ""
            if len(text) > PAGE_TEXT_LIMIT:
                raise ValueError("fixture_page_text_limit")
            observed_pages.append({"page": physical, "text": text})
            writer.add_page(page, excluded_keys=("/B", "/Annots"))
        out = BytesIO()
        writer.write(out)
        bounded = out.getvalue()
        if len(bounded) > PDF_MAX_BYTES:
            raise ValueError("fixture_selected_pdf_too_large")
        return {
            "page_count": count,
            "selected_physical_pages": selected,
            "physical_page_offset": selected[0],
            "retained_page_bounds": [selected[0], selected[-1]],
            "source_text": "\n\n".join(row["text"] for row in observed_pages).strip(),
            "source_pages": observed_pages,
            "selected_pdf": bounded,
            "document_sha256": sha256(payload).hexdigest(),
            "selected_pdf_sha256": sha256(bounded).hexdigest(),
            "source_text_sha256": sha256(
                "\n\n".join(row["text"] for row in observed_pages).strip().encode()
            ).hexdigest(),
            "parser_recovered": recovered,
        }
    except ValueError:
        raise
    except Exception:
        raise ValueError("fixture_pdf_parse_failed") from None


def _pypdf_extract(selected_pdf: bytes, physical_pages: list[int]) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(selected_pdf), strict=True)
    if reader.is_encrypted or len(reader.pages) != len(physical_pages):
        raise ValueError("selected_pdf_page_map_invalid")
    rows = []
    for offset, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if len(text) > PAGE_TEXT_LIMIT:
            raise ValueError("fixture_page_text_limit")
        rows.append({"page": physical_pages[offset], "text": text})
    text = "\n\n".join(row["text"] for row in rows).strip()
    if len(text) > TEXT_LIMIT:
        raise ValueError("fixture_window_text_limit")
    return {"text": text, "pages": rows, "page_map_available": True}


def _markitdown_pdf_extract(selected_pdf: bytes, converter, stream_info) -> dict:
    result = converter.convert(BytesIO(selected_pdf), stream_info)
    return {"text": result.text_content or "", "pages": [], "page_map_available": False}


@contextmanager
def _markitdown_model_tripwire():
    """Count and reject generic wrapper or Magika inference entry points."""
    from unittest.mock import patch

    import magika
    from markitdown import MarkItDown

    attempts = {
        "markitdown_constructor": 0,
        "markitdown_convert_stream": 0,
        "magika_constructor": 0,
        "magika_identify_stream": 0,
    }
    targets = (
        (MarkItDown, "__init__", "markitdown_constructor"),
        (MarkItDown, "convert_stream", "markitdown_convert_stream"),
        (magika.Magika, "__init__", "magika_constructor"),
        (magika.Magika, "identify_stream", "magika_identify_stream"),
    )

    def reject(name: str):
        def tripwire(*_args, **_kwargs):
            attempts[name] += 1
            raise RuntimeError(f"benchmark_model_tripwire:{name}")

        return tripwire

    with ExitStack() as stack:
        for target, attribute, name in targets:
            stack.enter_context(
                patch.object(target, attribute, new=reject(name))
            )
        yield attempts


def _trafilatura_extract(html: str) -> dict:
    import trafilatura

    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        include_links=False,
        favor_precision=True,
        with_metadata=False,
    )
    return {"text": text or "", "pages": [], "page_map_available": False}


def _measure(extract, warm_extract, repeats: int) -> dict:
    cold, latest = [], {}
    for _ in range(repeats):
        started = time.perf_counter()
        latest = extract()
        cold.append((time.perf_counter() - started) * 1000)
    warm_extract()
    warm = []
    for _ in range(repeats):
        started = time.perf_counter()
        latest = warm_extract()
        warm.append((time.perf_counter() - started) * 1000)
    peak, peak_kind = _peak_working_set()
    return {
        **_timing(cold, warm),
        "process_peak_rss_mib": peak,
        "rss_measurement": peak_kind,
        "text": latest.get("text", ""),
        "pages": latest.get("pages", []),
        "page_map_available": bool(latest.get("page_map_available")),
    }


def _preservation(result: dict, fixture: dict, fixed_physical_pages: list[int] | None) -> dict:
    text = _fold(result.get("text", ""))

    def strings(field: str) -> dict:
        expected = fixture.get(field, [])
        if not expected:
            return {"status": "UNKNOWN", "expected": 0, "found": 0, "missing": []}
        missing = [value for value in expected if _fold(value) not in text]
        return {
            "status": "PASS" if not missing else "FAIL",
            "expected": len(expected),
            "found": len(expected) - len(missing),
            "missing": missing,
        }

    expected_pages = fixture.get("expected_pages", [])
    if not expected_pages:
        pages = {"status": "NOT_APPLICABLE", "expected": 0, "found": 0}
    elif not result.get("page_map_available"):
        pages = {
            "status": "UNKNOWN",
            "expected": len(expected_pages),
            "found": None,
            "reason": "parser output has no physical page map; fixed selected pages are recorded separately",
        }
    else:
        observed = [row["page"] for row in result.get("pages", [])]
        missing = [page for page in expected_pages if page not in observed]
        pages = {
            "status": "PASS" if not missing else "FAIL",
            "expected": len(expected_pages),
            "found": len(expected_pages) - len(missing),
            "missing": missing,
        }
    fixed = {
        "status": "UNKNOWN" if fixed_physical_pages is None else "PASS",
        "physical_pages": fixed_physical_pages,
        "note": "physical pages are fixed by the fixture manifest, not inferred by this benchmark",
    }
    return {
        "pages": pages,
        "fixed_selected_physical_pages": fixed,
        "numbers": strings("expected_numbers"),
        "dates": strings("expected_dates"),
        "quotes": strings("expected_quotes"),
        "articles": strings("expected_articles"),
        "clauses": strings("expected_clauses"),
        "scope_note": "Fixture string checks do not establish legal correctness, legal effect, or faithfulness.",
    }


def _not_run(reason: str) -> dict:
    return {"status": "NOT RUN", "reason": reason}


def run_benchmark(manifest_path: Path, backend: str, repeats: int) -> dict:
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    if not isinstance(manifest.get("fixtures"), list):
        raise ValueError("fixture_manifest_invalid")
    blocked_network_entrypoints = _disable_network()
    packages = {
        name: _distribution(name)
        for name in (
            "pypdf",
            "markitdown",
            "pdfplumber",
            "pdfminer.six",
            "trafilatura",
        )
    }
    results = []
    model_tripwire_attempts = {
        "markitdown_constructor": 0,
        "markitdown_convert_stream": 0,
        "magika_constructor": 0,
        "magika_identify_stream": 0,
    }
    model_tripwire_measurements = 0
    model_tripwire_failures = []
    model_tripwire_unavailable = []
    for fixture in manifest["fixtures"]:
        path = (ROOT / fixture["path"]).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise ValueError("fixture_path_outside_repository_or_missing")
        raw = path.read_bytes()
        row = {
            "id": fixture["id"],
            "kind": fixture["kind"],
            "fixture_class": fixture.get("fixture_class"),
            "limitations": fixture.get("limitations", []),
            "input_sha256": sha256(raw).hexdigest(),
            "input_bytes": len(raw),
            "extractors": {},
        }
        if fixture["kind"] == "pdf":
            try:
                prepared = _prepare_selected_pdf(raw, fixture)
            except Exception as error:
                for name in ("pypdf", "markitdown_pdf"):
                    row["extractors"][name] = {
                        "status": "ERROR",
                        "reason": str(error)[:160],
                    }
                row["extractors"]["trafilatura_html"] = _not_run("fixture is PDF")
                row["extractors"]["current_html"] = _not_run("fixture is PDF")
                results.append(row)
                continue
            selected_pdf = prepared["selected_pdf"]
            physical_pages = prepared["selected_physical_pages"]
            for name in ("pypdf", "markitdown_pdf"):
                if (name == "pypdf" and backend not in {"all", "pypdf"}) or (
                    name == "markitdown_pdf" and backend not in {"all", "markitdown"}
                ):
                    row["extractors"][name] = _not_run(f"backend filter: {backend}")
                    continue
                if name == "markitdown_pdf" and not packages["markitdown"]["installed"]:
                    row["extractors"][name] = _not_run("optional dependency markitdown is unavailable")
                    continue
                try:
                    if name == "pypdf":
                        # Imports and fixture slicing are setup, outside parser timings.
                        from pypdf import PdfReader
                        parser = _pypdf_extract

                        def extract():
                            return parser(selected_pdf, physical_pages)

                        reader = None

                        def warm_extract():
                            nonlocal reader
                            if reader is None:
                                reader = PdfReader(BytesIO(selected_pdf), strict=True)
                            texts = [page.extract_text() or "" for page in reader.pages]
                            mapped = [
                                {"page": physical_pages[index], "text": text}
                                for index, text in enumerate(texts)
                            ]
                            return {
                                "text": "\n\n".join(texts).strip(),
                                "pages": mapped,
                                "page_map_available": True,
                            }
                    else:
                        # Use MarkItDown's explicit PDF converter; the generic
                        # wrapper constructs Magika and identifies every stream.
                        from markitdown._stream_info import StreamInfo
                        from markitdown.converters import PdfConverter

                        stream_info = StreamInfo(
                            mimetype="application/pdf",
                            extension=".pdf",
                            filename="fixture.pdf",
                        )

                        def extract():
                            return _markitdown_pdf_extract(
                                selected_pdf, PdfConverter(), stream_info
                            )

                        converter = None

                        def warm_extract():
                            nonlocal converter
                            if converter is None:
                                converter = PdfConverter()
                            return _markitdown_pdf_extract(
                                selected_pdf, converter, stream_info
                            )

                    if name == "markitdown_pdf":
                        attempts = None
                        measurement_completed = False
                        try:
                            with _markitdown_model_tripwire() as attempts:
                                measured = _measure(extract, warm_extract, repeats)
                                measurement_completed = True
                        finally:
                            if attempts is None:
                                model_tripwire_unavailable.append(fixture["id"])
                            else:
                                if measurement_completed:
                                    model_tripwire_measurements += 1
                                for key, count in attempts.items():
                                    model_tripwire_attempts[key] += count
                        measured["model_inference_tripwire"] = {
                            "status": "PASS"
                            if not any(attempts.values())
                            else "FAIL",
                            "attempts": attempts,
                        }
                    else:
                        measured = _measure(extract, warm_extract, repeats)
                    measured.update(
                        status="OK",
                        version=(
                            packages["pypdf"]["version"]
                            if name == "pypdf"
                            else packages["markitdown"]["version"]
                        ),
                        page_count=prepared["page_count"],
                        selected_physical_pages=physical_pages,
                        physical_page_offset=physical_pages[0],
                        retained_page_bounds=prepared["retained_page_bounds"],
                        page_map_available=bool(measured["page_map_available"]),
                        document_sha256=prepared["document_sha256"],
                        selected_pdf_sha256=prepared["selected_pdf_sha256"],
                        text_sha256=sha256(measured["text"].encode()).hexdigest(),
                        extraction_version="fixed-page-parser-benchmark-v2",
                    )
                    if name == "markitdown_pdf":
                        measured.update(
                            reader="markitdown.converters.PdfConverter",
                            conversion_api="convert(stream, StreamInfo(mimetype='application/pdf', extension='.pdf'))",
                        )
                    measured["preservation"] = _preservation(
                        measured, fixture, physical_pages
                    )
                    measured.pop("text", None)
                    measured.pop("pages", None)
                    row["extractors"][name] = measured
                except Exception as error:
                    if name == "markitdown_pdf":
                        model_tripwire_failures.append(fixture["id"])
                    row["extractors"][name] = {
                        "status": "ERROR",
                        "reason": f"{type(error).__name__}: {str(error)[:160]}",
                    }
            row["extractors"]["trafilatura_html"] = _not_run("fixture is PDF")
            row["extractors"]["current_html"] = _not_run("fixture is PDF")
            row["selection_preparation"] = {
                "status": "OK",
                "strategy": "manifest_fixed_physical_pages",
                "page_selection_ms": "NOT MEASURED",
                "document_sha256": prepared["document_sha256"],
                "selected_pdf_sha256": prepared["selected_pdf_sha256"],
                "source_pypdf_text_sha256": prepared["source_text_sha256"],
                "parser_recovered": prepared["parser_recovered"],
                "note": "Both PDF parser backends receive identical selected_pdf bytes; page selection is held constant, not benchmarked.",
            }
        elif fixture["kind"] == "html":
            html = raw.decode("utf-8", errors="strict")
            if backend not in {"all", "trafilatura"}:
                row["extractors"]["trafilatura_html"] = _not_run(f"backend filter: {backend}")
            elif not packages["trafilatura"]["installed"]:
                row["extractors"]["trafilatura_html"] = _not_run(
                    "optional dependency trafilatura is unavailable"
                )
            else:
                try:
                    # Import Trafilatura before timing the extraction calls.
                    import_module("trafilatura")

                    row["extractors"]["trafilatura_html"] = _measure(
                        lambda: _trafilatura_extract(html),
                        lambda: _trafilatura_extract(html),
                        repeats,
                    )
                    result = row["extractors"]["trafilatura_html"]
                    result.update(
                        status="OK",
                        version=packages["trafilatura"]["version"],
                        input_sha256=sha256(raw).hexdigest(),
                        text_sha256=sha256(result["text"].encode()).hexdigest(),
                        extraction_version="offline-trafilatura-benchmark-v1",
                    )
                    result["preservation"] = _preservation(result, fixture, None)
                    result.pop("text", None)
                    result.pop("pages", None)
                except Exception as error:
                    row["extractors"]["trafilatura_html"] = {
                        "status": "ERROR",
                        "reason": f"{type(error).__name__}: {str(error)[:160]}",
                    }
            row["extractors"]["pypdf"] = _not_run("fixture is HTML")
            row["extractors"]["markitdown_pdf"] = _not_run(
                "HTML comparison uses Trafilatura only"
            )
            if backend not in {"all", "current-html"}:
                row["extractors"]["current_html"] = _not_run(
                    f"backend filter: {backend}"
                )
            else:
                try:
                    # Load the actual local HTML reader only after network
                    # connections and DNS have been disabled above.
                    from app.services import trusted_source_reader

                    extract_page = trusted_source_reader.extract_page
                    reader_path = Path(trusted_source_reader.__file__).resolve()
                    reader_source_sha256 = sha256(reader_path.read_bytes()).hexdigest()
                    reader_url = fixture.get("reader_test_url", CURRENT_HTML_TEST_URL)

                    def extract_current_html():
                        page = extract_page(html, reader_url)
                        return {
                            "text": page["text"],
                            "pages": [],
                            "page_map_available": False,
                        }

                    measured = _measure(
                        extract_current_html,
                        extract_current_html,
                        repeats,
                    )
                    measured.update(
                        status="OK",
                        reader="app.services.trusted_source_reader.extract_page",
                        reader_source_path=reader_path.relative_to(ROOT).as_posix()
                        if ROOT in reader_path.parents
                        else reader_path.name,
                        reader_source_sha256=reader_source_sha256,
                        reader_test_url=reader_url,
                        input_sha256=sha256(raw).hexdigest(),
                        fixture_source_sha256=sha256(raw).hexdigest(),
                        text_sha256=sha256(measured["text"].encode()).hexdigest(),
                        extraction_version="visible_html_text",
                        page_map_available=False,
                        fixture_limitations=list(fixture.get("limitations", []))
                        + [
                            "One fixed synthetic HTML fixture; not evidence of reader quality across official websites."
                        ],
                    )
                    measured["preservation"] = _preservation(
                        measured, fixture, None
                    )
                    measured.pop("text", None)
                    measured.pop("pages", None)
                    row["extractors"]["current_html"] = measured
                except Exception as error:
                    row["extractors"]["current_html"] = {
                        "status": "ERROR",
                        "reason": f"{type(error).__name__}: {str(error)[:160]}",
                    }
        else:
            row["extractors"] = {"status": "NOT RUN", "reason": "unsupported fixture kind"}
        results.append(row)

    stack_names = ("markitdown", "pdfplumber", "pdfminer.six")
    stack_complete = all(
        packages[name]["installed"] and packages[name]["files_bytes"] is not None
        for name in stack_names
    )
    markitdown_stack_bytes = (
        sum(packages[name]["files_bytes"] for name in stack_names)
        if stack_complete
        else None
    )
    pypdf_bytes = packages["pypdf"]["files_bytes"]
    script_path = Path(__file__).resolve()
    return {
        "schema_version": "document-readers-benchmark-v4",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "command": sys.argv,
        "backend_filter": backend,
        "repeat_count": repeats,
        "execution": {
            "network": {
                "status": "SOCKET_API_GUARDED",
                "blocked_entrypoints": blocked_network_entrypoints,
                "scope": (
                    "Only the listed Python socket connection, DNS, and available "
                    "datagram-send entry points are blocked; this is not a "
                    "process-wide or OS-level network sandbox."
                ),
            },
            "model_inference_tripwire": {
                "status": (
                    "FAIL"
                    if any(model_tripwire_attempts.values())
                    else "INCOMPLETE"
                    if model_tripwire_failures
                    else "PARTIAL"
                    if model_tripwire_unavailable and model_tripwire_measurements
                    else "UNAVAILABLE"
                    if model_tripwire_unavailable
                    else "PASS"
                    if model_tripwire_measurements
                    else "NOT RUN"
                ),
                "scope": (
                    "MarkItDown PDF-only benchmark using PdfConverter directly; "
                    "generic MarkItDown construction/convert_stream and Magika "
                    "construction/identify_stream are counted and raise if called."
                ),
                "completed_measurements": model_tripwire_measurements,
                "attempts": model_tripwire_attempts,
                "failed_fixtures": model_tripwire_failures,
                "unavailable_fixtures": model_tripwire_unavailable,
            },
            "remote_urls": 0,
            "upload_bytes": 0,
            "provider_calls": 0,
            "process_startup_in_timings": False,
        },
        "python": sys.version,
        "platform": platform.platform(),
        "benchmark_script": {
            "path": (
                script_path.relative_to(ROOT).as_posix()
                if ROOT in script_path.parents
                else script_path.name
            ),
            "sha256": sha256(script_path.read_bytes()).hexdigest(),
        },
        "fixture_manifest": {
            "path": (
                str(manifest_path.relative_to(ROOT))
                if ROOT in manifest_path.parents
                else str(manifest_path)
            ),
            "sha256": sha256(raw_manifest).hexdigest(),
            "purpose": manifest.get("purpose"),
        },
        "dependencies": packages,
        "optional_bundle_size_estimate": {
            "markitdown_pdf_direct_distributions_status": (
                "ESTIMATE" if stack_complete else "UNKNOWN_INCOMPLETE_DISTRIBUTIONS"
            ),
            "markitdown_pdf_direct_distributions_bytes": markitdown_stack_bytes,
            "pypdf_distribution_files_bytes": pypdf_bytes,
            "delta_bytes_vs_pypdf": (
                markitdown_stack_bytes - pypdf_bytes
                if pypdf_bytes is not None and markitdown_stack_bytes is not None
                else None
            ),
            "scope": "Installed direct distribution file sizes; not the full dependency closure or deployment-bundle proof.",
        },
        "results": results,
        "claim_policy": (
            "Reports fixture measurements only. No speed, legal-quality, or production-readiness claim is inferred."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--backend",
        choices=("all", "pypdf", "markitdown", "trafilatura", "current-html"),
        default="all",
    )
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 25:
        parser.error("--repeat must be between 1 and 25")
    if args.output and args.output.exists():
        parser.error("--output already exists; refusing to overwrite")
    manifest = args.manifest.resolve()
    if not manifest.is_file():
        parser.error("fixture manifest does not exist")
    result = run_benchmark(manifest, args.backend, args.repeat)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
