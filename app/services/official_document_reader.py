"""Bounded official PDF page windows with explicit scan and OCR provenance."""

import asyncio
import json
import os
import re
import signal
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import struct
import subprocess
import sys

from app.services.runtime_errors import SourceReadError

PDF_MAX_BYTES = 20_000_000
PAGE_WINDOW = 5
TEXT_LIMIT = 20_000
SMART_WORKER_TIMEOUT_SECONDS = 15
EXTRACTION_VERSION = "official-pdf-reader-v2"
_WORKER_OUTPUT_LIMIT = PDF_MAX_BYTES + 2_000_000
_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS = 1.0
_WINDOWS_WORKER_BOOTSTRAP = (
    "import sys; "
    "sys.stdin.buffer.read(1); "
    "import os,runpy,site; "
    "venv,root=sys.argv[1:3]; "
    "sys.prefix=sys.exec_prefix=venv; "
    "site.addsitedir(os.path.join(venv,'Lib','site-packages')); "
    "sys.path.insert(0,root); "
    "sys.argv=['app.services.official_pdf_worker']; "
    "runpy.run_module('app.services.official_pdf_worker',run_name='__main__')"
)


def _pdf_reader(payload: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        return PdfReader(BytesIO(payload), strict=True), False
    except PdfReadError:
        try:
            return PdfReader(BytesIO(payload), strict=False), True
        except Exception:
            raise SourceReadError("source_malformed_pdf") from None
    except Exception:
        raise SourceReadError("source_malformed_pdf") from None


def _page_count(reader) -> int:
    try:
        if reader.is_encrypted:
            raise SourceReadError("source_encrypted_pdf")
        count = len(reader.pages)
    except SourceReadError:
        raise
    except Exception:
        raise SourceReadError("source_malformed_pdf") from None
    if not 1 <= count <= 200:
        raise SourceReadError("source_pdf_page_limit")
    return count


def _page_text(reader, page_number: int) -> str:
    try:
        text = reader.pages[page_number - 1].extract_text() or ""
    except Exception:
        raise SourceReadError("source_malformed_pdf") from None
    if len(text) > TEXT_LIMIT:
        raise SourceReadError("source_page_text_limit")
    return text


def _window(payload: bytes, page_start: int, use_ocr: bool, page_limit: int):
    from pypdf import PdfWriter

    try:
        reader, recovered = _pdf_reader(payload)
        count = _page_count(reader)
        if not 1 <= page_start <= count:
            raise SourceReadError("source_page_out_of_range")
        if not 1 <= page_limit <= PAGE_WINDOW:
            raise SourceReadError("source_page_window_invalid")
        end = min(count, page_start + page_limit - 1)
        pages = []
        writer = PdfWriter()
        for page_number in range(page_start, end + 1):
            page = reader.pages[page_number - 1]
            pages.append({"page": page_number, "text": _page_text(reader, page_number)})
            if use_ocr:
                # Signature/widget references can pull the whole PDF into a page slice.
                writer.add_page(page, excluded_keys=("/B", "/Annots"))
        batch = None
        if use_ocr:
            output = BytesIO()
            writer.write(output)
            batch = output.getvalue()
        return count, pages, batch, recovered
    except SourceReadError:
        raise
    except Exception:
        raise SourceReadError("source_malformed_pdf") from None


def _query_profile(question: str):
    from app.services.legal_topic_terms import (
        extract_official_topic_phrases,
        fold_topic_text,
        local_rescue_terms,
    )

    query = str(question or "")[:2_000]
    terms = set(local_rescue_terms(query, limit=32))
    article_numbers = {
        int(number)
        for number in re.findall(r"\b(?:điều|dieu)\s+(\d{1,4})\b", query, re.I)
    }
    phrases = tuple(
        fold_topic_text(phrase)
        for phrase in extract_official_topic_phrases(query, limit=8)
    )
    return terms, article_numbers, phrases


def _relevance_score(text: str, profile) -> int:
    from app.services.legal_topic_terms import fold_topic_text, local_rescue_terms

    terms, article_numbers, phrases = profile
    candidate = fold_topic_text(text)
    score = 3 * len(terms & set(local_rescue_terms(text, limit=64)))
    score += 6 * sum(1 for phrase in phrases if phrase and phrase in candidate)
    score += 20 * sum(
        1
        for number in article_numbers
        if re.search(rf"(?<![a-z0-9])dieu\s+{number}(?!\d)", candidate)
    )
    return score


def _outline_scores(reader, page_count: int, profile) -> dict[int, int]:
    """Match question terms against real bookmark and named-destination labels."""
    scores: dict[int, int] = {}
    seen = 0

    def add(label, destination):
        nonlocal seen
        if seen >= 1_000:
            return
        seen += 1
        if not isinstance(label, str) or not label.strip():
            return
        score = _relevance_score(label, profile)
        if score <= 0:
            return
        try:
            page = reader.get_destination_page_number(destination)
        except Exception:
            return
        if isinstance(page, int) and not isinstance(page, bool) and 0 <= page < page_count:
            number = page + 1
            scores[number] = max(scores.get(number, 0), score)

    try:
        pending = [(reader.outline or [], 0)]
        while pending and seen < 1_000:
            node, depth = pending.pop()
            if isinstance(node, list):
                if depth < 20:
                    pending.extend((child, depth + 1) for child in reversed(node))
                continue
            add(getattr(node, "title", ""), node)
        destinations = reader.named_destinations
        for name, destination in list(destinations.items())[: max(0, 1_000 - seen)]:
            label = str(getattr(destination, "title", "") or name)
            add(label, destination)
    except Exception:
        # Broken optional navigation metadata must not block bounded text reads.
        pass
    return scores


def _best_window(page_count: int, window_size: int, scores: dict[int, int]) -> int:
    length = min(window_size, page_count)
    best_start = 1
    best_key = None
    positive = [(page, score) for page, score in scores.items() if score > 0]
    for start in range(1, page_count - length + 2):
        end = start + length - 1
        inside = [(page, score) for page, score in positive if start <= page <= end]
        score = sum(value for _, value in inside)
        center = (start + end) / 2
        distance = min((abs(center - page) for page, _ in inside), default=0)
        key = (score, len(inside), -distance, -start)
        if best_key is None or key > best_key:
            best_key, best_start = key, start
    return best_start


def _probe_pages(page_count: int) -> list[int]:
    return sorted(
        {
            1,
            *(((page_count * quartile + 3) // 4) for quartile in (1, 2, 3)),
            page_count,
        }
    )


def _smart_window(payload: bytes, question: str, use_ocr: bool, page_limit: int, *, deep_read: bool = False):
    """Extract a bounded contiguous window after navigation match or five-page probe."""
    from pypdf import PdfWriter

    reader, recovered = _pdf_reader(payload)
    count = _page_count(reader)
    if not 1 <= page_limit <= (20 if deep_read else PAGE_WINDOW) or (deep_read and use_ocr):
        raise SourceReadError("source_page_window_invalid")
    profile = _query_profile(question)
    outline_scores = _outline_scores(reader, count, profile)
    inspected: list[int] = []
    page_texts: dict[int, str] = {}

    def inspect(page_number: int):
        if page_number not in page_texts:
            if len(inspected) >= (40 if deep_read else 10):
                raise SourceReadError("source_inspection_limit")
            page_texts[page_number] = _page_text(reader, page_number)
            inspected.append(page_number)

    if deep_read:
        # Reserve twenty inspections for the contiguous retained window.
        probes = (list(range(1, count + 1)) if count <= 40 else
                  sorted({1 + round(i * (count - 1) / 19) for i in range(20)}))
        if count > 40 and outline_scores:
            probes = list(dict.fromkeys([*sorted(outline_scores, key=outline_scores.get, reverse=True)[:10], *probes]))[:20]
        for page_number in probes:
            inspect(page_number)
        scores = {number: _relevance_score(text, profile) + outline_scores.get(number, 0)
                  for number, text in page_texts.items()}
        start = _best_window(count, page_limit, scores)
        selection_status = "probe_match" if max(scores.values(), default=0) else "no_evidence_in_probe"
    elif outline_scores:
        start = _best_window(count, page_limit, outline_scores)
        selection_status = "outline_match"
    else:
        probes = _probe_pages(count)
        for page_number in probes:
            inspect(page_number)
        probe_scores = {
            number: _relevance_score(text, profile)
            for number, text in page_texts.items()
        }
        start = _best_window(count, page_limit, probe_scores)
        if not profile[0] and not profile[1] and not profile[2]:
            selection_status = "no_question_terms"
        elif max(probe_scores.values(), default=0) > 0:
            selection_status = "probe_match"
        else:
            selection_status = "no_evidence_in_probe"

    end = min(count, start + page_limit - 1)
    selected = list(range(start, end + 1))
    for page_number in selected:
        inspect(page_number)
    pages = [
        {"page": number, "text": page_texts[number]} for number in selected
    ]
    full_text = "\n\n".join(page["text"] for page in pages).strip()
    if profile[1] and full_text:
        from app.services.legal_topic_terms import fold_topic_text
        retained = fold_topic_text(full_text)
        if not any(re.search(rf'\bdieu\s+{number}(?!\d)', retained) for number in profile[1]):
            raise SourceReadError('source_requested_article_not_found')
    if len(full_text) > (240_000 if deep_read else TEXT_LIMIT):
        raise SourceReadError("source_page_window_text_limit")
    batch = None
    if use_ocr:
        writer = PdfWriter()
        for page_number in selected:
            writer.add_page(
                reader.pages[page_number - 1], excluded_keys=("/B", "/Annots")
            )
        output = BytesIO()
        writer.write(output)
        batch = output.getvalue()
        if len(batch) > PDF_MAX_BYTES:
            raise SourceReadError("source_processing_limit")
    return {
        "page_count": count,
        "pages": pages,
        "parser_recovered": recovered,
        "inspected_pages": inspected,
        "smart_selection_status": selection_status,
    }, batch


def _create_windows_worker_job(process):
    """Assign the gated worker to a retained kill-on-close Job Object."""
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [
            ("process_time", c.c_int64),
            ("job_time", c.c_int64),
            ("flags", w.DWORD),
            ("min_ws", c.c_size_t),
            ("max_ws", c.c_size_t),
            ("active", w.DWORD),
            ("affinity", c.c_size_t),
            ("priority", w.DWORD),
            ("scheduling", w.DWORD),
        ]

    class Extended(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", c.c_uint64 * 6),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError(c.get_last_error(), "CreateJobObjectW failed")
    try:
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
            raise OSError(c.get_last_error(), "SetInformationJobObject failed")
        child = kernel.OpenProcess(0x0101, False, process.pid)  # SET_QUOTA | TERMINATE
        if not child:
            raise OSError(c.get_last_error(), "OpenProcess failed")
        try:
            if not kernel.AssignProcessToJobObject(job, child):
                raise OSError(c.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            kernel.CloseHandle(child)
        return job
    except Exception:
        kernel.CloseHandle(job)
        raise


def _terminate_windows_worker_job(job):
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    kernel.TerminateJobObject.restype = w.BOOL
    if not kernel.TerminateJobObject(job, 1):
        raise OSError(c.get_last_error(), "TerminateJobObject failed")


def _close_windows_worker_job(job):
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle(job)


async def _kill_and_reap(process, communication, windows_job=None):
    cancelled = False
    process_id = getattr(process, "pid", None)
    if windows_job is not None:
        try:
            _terminate_windows_worker_job(windows_job)
        except OSError:
            # The caller closes the retained kill-on-close handle after bounded reap.
            pass
    elif process_id is not None and os.name != "nt":
        try:
            os.killpg(process_id, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    if process.returncode is None:
        try:
            process.kill()
        except (ProcessLookupError, OSError):
            pass

    process_wait = asyncio.create_task(process.wait())
    try:
        await asyncio.wait_for(
            asyncio.shield(process_wait),
            timeout=_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        cancelled = True
        try:
            await asyncio.wait_for(
                asyncio.shield(process_wait),
                timeout=_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError, asyncio.CancelledError):
            pass
    except (OSError, TimeoutError):
        pass

    try:
        await asyncio.wait_for(
            asyncio.shield(communication),
            timeout=_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        cancelled = True
        try:
            await asyncio.wait_for(
                asyncio.shield(communication),
                timeout=_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS,
            )
        except (OSError, TimeoutError, asyncio.CancelledError, ValueError):
            communication.cancel()
            try:
                await asyncio.wait_for(communication, timeout=0.1)
            except (Exception, asyncio.CancelledError):
                cancelled |= asyncio.current_task().cancelling() > 0
    except (OSError, TimeoutError, ValueError):
        communication.cancel()
        try:
            await asyncio.wait_for(communication, timeout=0.1)
        except asyncio.CancelledError:
            cancelled |= asyncio.current_task().cancelling() > 0
        except Exception:
            pass

    if not process_wait.done():
        process_wait.cancel()
    if cancelled:
        raise asyncio.CancelledError


def _decode_worker_output(stdout: bytes, *, deep_read: bool = False):
    if len(stdout) < 4:
        raise SourceReadError("source_processing_failed")
    header_size = struct.unpack("!I", stdout[:4])[0]
    if not 1 <= header_size <= 1_000_000 or 4 + header_size > len(stdout):
        raise SourceReadError("source_processing_failed")
    try:
        response = json.loads(stdout[4 : 4 + header_size])
    except (ValueError, TypeError):
        raise SourceReadError("source_processing_failed") from None
    if not isinstance(response, dict):
        raise SourceReadError("source_processing_failed")
    if "error" in response:
        kind = response.get("error")
        if isinstance(kind, str) and 0 < len(kind) <= 100:
            raise SourceReadError(kind)
        raise SourceReadError("source_processing_failed")
    batch_size = response.pop("ocr_input_length", 0)
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 0 <= batch_size <= PDF_MAX_BYTES
        or len(stdout) != 4 + header_size + batch_size
    ):
        raise SourceReadError("source_processing_output_invalid")
    count = response.get("page_count")
    pages = response.get("pages")
    inspected = response.get("inspected_pages")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 1 <= count <= 200
        or not isinstance(pages, list)
        or not 1 <= len(pages) <= (20 if deep_read else PAGE_WINDOW)
        or not isinstance(inspected, list)
        or len(inspected) > (40 if deep_read else 10)
        or any(not isinstance(number, int) or isinstance(number, bool) for number in inspected)
        or len(set(inspected)) != len(inspected)
        or any(
            not isinstance(number, int)
            or isinstance(number, bool)
            or not 1 <= number <= count
            for number in inspected
        )
    ):
        raise SourceReadError("source_processing_output_invalid")
    numbers = []
    for page in pages:
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("page"), int)
            or isinstance(page.get("page"), bool)
            or not 1 <= page["page"] <= count
            or not isinstance(page.get("text"), str)
            or len(page["text"]) > TEXT_LIMIT
        ):
            raise SourceReadError("source_processing_output_invalid")
        numbers.append(page["page"])
    if numbers != list(range(numbers[0], numbers[-1] + 1)) or any(
        number not in inspected for number in numbers
    ):
        raise SourceReadError("source_processing_output_invalid")
    if response.get("smart_selection_status") not in {
        "outline_match",
        "probe_match",
        "no_evidence_in_probe",
        "no_question_terms",
    }:
        raise SourceReadError("source_processing_output_invalid")
    response["ocr_input"] = stdout[4 + header_size :]
    return response


async def _extract_smart_isolated(
    payload: bytes, *, question: str, use_ocr: bool, page_limit: int, deep_read: bool = False
):
    metadata = json.dumps(
        {
            "payload_length": len(payload),
            "question": str(question or "")[:2_000],
            "use_ocr": bool(use_ocr),
            "page_limit": page_limit,
            "deep_read": deep_read,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    if len(metadata) > 16_384:
        raise SourceReadError("source_processing_request_invalid")
    frame = bytearray(4 + len(metadata) + len(payload))
    struct.pack_into("!I", frame, 0, len(metadata))
    frame[4 : 4 + len(metadata)] = metadata
    frame[4 + len(metadata) :] = payload
    try:
        spawn_options = {}
        if os.name != "nt":
            spawn_options["start_new_session"] = True
            command = [sys.executable, "-m", "app.services.official_pdf_worker"]
        else:
            command = [
                getattr(sys, "_base_executable", sys.executable),
                "-I",
                "-S",
                "-c",
                _WINDOWS_WORKER_BOOTSTRAP,
                str(sys.prefix),
                str(Path(__file__).resolve().parents[2]),
            ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parents[2],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            **spawn_options,
        )
    except (OSError, NotImplementedError):
        raise SourceReadError("source_processing_unavailable") from None
    windows_job = None
    worker_input = frame
    if os.name == "nt" and getattr(process, "pid", None) is not None:
        try:
            windows_job = _create_windows_worker_job(process)
            worker_input = b"\0" + frame
        except OSError:
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass
            try:
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=_WORKER_CLEANUP_STEP_TIMEOUT_SECONDS,
                )
            except (OSError, TimeoutError, ValueError):
                pass
            raise SourceReadError("source_processing_unavailable") from None
    communication = asyncio.create_task(process.communicate(input=worker_input))
    try:
        stdout, _ = await asyncio.wait_for(
            asyncio.shield(communication), timeout=SMART_WORKER_TIMEOUT_SECONDS
        )
    except TimeoutError:
        await _kill_and_reap(process, communication, windows_job)
        raise SourceReadError("source_processing_timeout") from None
    except asyncio.CancelledError:
        await _kill_and_reap(process, communication, windows_job)
        raise
    except (OSError, ValueError):
        await _kill_and_reap(process, communication, windows_job)
        raise SourceReadError("source_processing_unavailable") from None
    finally:
        if windows_job is not None:
            _close_windows_worker_job(windows_job)
    if process.returncode or len(stdout) > _WORKER_OUTPUT_LIMIT:
        raise SourceReadError("source_processing_limit")
    return _decode_worker_output(stdout, deep_read=True) if deep_read else _decode_worker_output(stdout)


def _make_result(
    payload: bytes,
    *,
    url: str,
    attachment_url: str,
    title: str,
    count: int,
    pages: list[dict],
    recovered: bool,
    inspected_pages: list[int],
    smart_selection_status: str | None = None,
):
    start, end = pages[0]["page"], pages[-1]["page"]
    result = {
        "url": url,
        "attachment_url": attachment_url,
        "title": title or attachment_url.rsplit("/", 1)[-1],
        "document_sha256": sha256(payload).hexdigest(),
        "parser_recovered": recovered,
        "ocr_input_sha256": None,
        "ocr_input_transform": None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "method": "pdf_text",
        "legal_effect_status": "unverified",
        "document_number": None,
        "pages": pages,
        "page_count": count,
        "page_start": start,
        "page_end": end,
        "next_page_start": end + 1 if end < count else None,
        "truncated": start > 1 or end < count,
        "inspected_pages": inspected_pages,
        "inspected_page_count": len(inspected_pages),
        "extraction_version": EXTRACTION_VERSION,
        "ocr_provider": None,
        "ocr_model": None,
    }
    if smart_selection_status is not None:
        result["smart_selection_status"] = smart_selection_status
    return result


def _finalize_result(result: dict, *, use_ocr: bool):
    full_text = "\n\n".join(page["text"] for page in result["pages"]).strip()
    if len(full_text) > (240_000 if result.get("deep_read") else TEXT_LIMIT):
        raise SourceReadError("source_page_window_text_limit")
    digest = sha256(full_text.encode()).hexdigest()
    missing = [page["page"] for page in result["pages"] if not page["text"].strip()]
    result.update(
        text=full_text,
        sha256=digest,
        text_sha256=digest,
        extracted_characters=len(full_text),
        stored_characters=len(full_text),
        partial_read=result["truncated"],
        content_status="readable" if full_text else "metadata_only",
        requires_ocr=bool(missing) and not use_ocr,
        unreadable_pages=missing,
    )
    return result


async def _apply_ocr(result: dict, batch: bytes):
    from app.services.workspace_documents import DocumentExtractionError
    from app.services.workspace_ocr import extract_ocr_document

    try:
        document = await extract_ocr_document("official-pages.pdf", "application/pdf", batch)
    except DocumentExtractionError as error:
        raise SourceReadError(str(error)) from None
    original_pages = result["pages"]
    local_text = {
        index: "\n\n".join(
            clause.text for clause in document.clauses if clause.page == index
        )
        for index in range(1, len(original_pages) + 1)
    }
    result["pages"] = [
        {"page": page["page"], "text": local_text[index]}
        for index, page in enumerate(original_pages, 1)
    ]
    result["method"] = "vertex_ocr"
    result["ocr_input_sha256"] = sha256(batch).hexdigest()
    result["ocr_input_transform"] = "selected_page_content_without_annotations"
    result["ocr_provider"] = document.ocr_provider
    result["ocr_model"] = document.ocr_model


async def extract_official_pdf(
    payload: bytes,
    *,
    url: str,
    attachment_url: str,
    title: str = "",
    page_start: int = 1,
    use_ocr: bool = False,
    page_limit: int = PAGE_WINDOW,
    question: str = "",
    smart_pages: bool = False,
    deep_read: bool = False,
):
    if len(payload) > PDF_MAX_BYTES or not payload.startswith(b"%PDF-"):
        raise SourceReadError("source_pdf_body_invalid")
    if deep_read and (use_ocr or not smart_pages):
        raise SourceReadError("source_deep_read_mode_invalid")
    if smart_pages:
        extracted = await _extract_smart_isolated(
            payload, question=question, use_ocr=use_ocr, page_limit=page_limit,
            **({"deep_read": True} if deep_read else {}),
        )
        batch = extracted.pop("ocr_input")
        result = _make_result(
            payload,
            url=url,
            attachment_url=attachment_url,
            title=title,
            count=extracted["page_count"],
            pages=extracted["pages"],
            recovered=extracted["parser_recovered"],
            inspected_pages=extracted["inspected_pages"],
            smart_selection_status=extracted["smart_selection_status"],
        )
    else:
        count, pages, batch, recovered = await asyncio.to_thread(
            _window, payload, page_start, use_ocr, page_limit
        )
        result = _make_result(
            payload,
            url=url,
            attachment_url=attachment_url,
            title=title,
            count=count,
            pages=pages,
            recovered=recovered,
            inspected_pages=[page["page"] for page in pages],
        )
    if use_ocr:
        await _apply_ocr(result, batch)
    if deep_read:
        result["deep_read"] = True
    return _finalize_result(result, use_ocr=use_ocr)
