from io import BytesIO
import pytest
import httpx
from pypdf import PdfWriter

from app.services.trusted_source_reader import read_source, SourceReadError


def blank_pdf(pages=6):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=400)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def text_pdf(page_texts, *, outline=None):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for page_number, value in enumerate(page_texts, 1):
        page = writer.add_blank_page(width=300, height=400)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 12 Tf 20 350 Td ("
            + value.encode("ascii", errors="replace")
            + b") Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        for title, target in outline or []:
            if target == page_number:
                writer.add_outline_item(title, page_number - 1)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_smart_reader_rejects_keyword_window_missing_requested_article():
    from app.services.official_document_reader import _smart_window
    pages = ['Dieu 10. Cong doan tien luong thu viec'] * 20
    pages[8] = 'Dieu 25. Thoi gian thu viec toi da 60 ngay.'
    with pytest.raises(SourceReadError, match='source_requested_article_not_found'):
        _smart_window(text_pdf(pages), 'Điều 25 thời gian thử việc', False, 5)


def test_smart_reader_retains_window_with_requested_article():
    from app.services.official_document_reader import _smart_window
    pages = ['Dieu 10. Cong doan tien luong'] * 20
    pages[9] = 'Dieu 25. Thoi gian thu viec toi da 60 ngay.'
    result, _ = _smart_window(text_pdf(pages), 'Điều 25 thời gian thử việc', False, 5)
    assert any('Dieu 25.' in page['text'] for page in result['pages'])
    assert len(result['inspected_pages']) <= 10


@pytest.mark.asyncio
async def test_official_attachment_reads_pages_not_navigation_and_marks_scan():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if request.url.host == "vanban.chinhphu.vn":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<title>Quy định</title><nav>Menu</nav><table><tr><td>Số ký hiệu</td><td>1/2026/NĐ-CP</td></tr><tr><td>Ngày có hiệu lực</td><td>09-09-2026</td></tr></table><a href="https://datafiles.chinhphu.vn/law.pdf">Bản ký</a>',
            )
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=blank_pdf()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await read_source(
            "https://vanban.chinhphu.vn/?docid=123", client=client
        )
    assert len(urls) == 2
    assert result["text"] == ""
    assert result["requires_ocr"] is True
    assert result["page_count"] == 6 and result["next_page_start"] == 6
    assert result["attachment_url"] == "https://datafiles.chinhphu.vn/law.pdf"
    assert result["legal_effect_status"] == "unverified"
    assert result["document_number"] == "1/2026/NĐ-CP"
    assert result["reported_effective_from"] == "09-09-2026"


@pytest.mark.asyncio
async def test_reader_never_fetches_unapproved_attachment():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<title>Law</title><a href="https://evil.test/law.pdf">Bản ký</a>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await read_source("https://vanban.chinhphu.vn/?docid=1", client=client)
    assert len(seen) == 1
    assert result.get("content_status") == "metadata_only"


@pytest.mark.asyncio
async def test_pdf_page_window_rejects_out_of_range():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=blank_pdf(2)
            )
        )
    ) as client:
        with pytest.raises(SourceReadError, match="source_page_out_of_range"):
            await read_source(
                "https://datafiles.chinhphu.vn/law.pdf", page_start=3, client=client
            )


@pytest.mark.asyncio
async def test_caller_can_reduce_window_without_losing_page_position():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf"}, content=blank_pdf()
            )
        )
    ) as client:
        result = await read_source(
            "https://datafiles.chinhphu.vn/law.pdf",
            page_start=3,
            page_limit=1,
            client=client,
        )
    assert (
        result["page_start"] == 3
        and result["page_end"] == 3
        and result["next_page_start"] == 4
    )


def test_ocr_window_does_not_clone_annotation_document_graph():
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )
    from app.services.official_document_reader import _window

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    page[NameObject("/Annots")] = ArrayObject(
        [
            writer._add_object(
                DictionaryObject(
                    {NameObject("/Contents"): TextStringObject("annotation-only")}
                )
            )
        ]
    )
    out = BytesIO()
    writer.write(out)
    result = _window(out.getvalue(), 1, True, 1)
    from pypdf import PdfReader

    assert not PdfReader(BytesIO(result[2])).pages[0].get("/Annots")


@pytest.mark.asyncio
async def test_recoverable_pdf_metadata_is_flagged_instead_of_rejecting_page_content():
    from app.services.official_document_reader import extract_official_pdf

    payload = blank_pdf(1).replace(b"/Size", b"/Info 1 0 R\n/Size", 1)
    result = await extract_official_pdf(
        payload,
        url="https://datafiles.chinhphu.vn/a.pdf",
        attachment_url="https://datafiles.chinhphu.vn/a.pdf",
    )
    assert result["parser_recovered"] is True
    assert result["page_count"] == 1


@pytest.mark.asyncio
async def test_smart_pdf_probes_and_retains_best_contiguous_window_with_physical_pages():
    from app.services.official_document_reader import extract_official_pdf

    payload = text_pdf(
        ["unrelated text"] * 14
        + ["Trach nhiem nguoi su dung lao dong va thoi han tra luong"]
        + ["unrelated text"] * 5
    )
    result = await extract_official_pdf(
        payload,
        url="https://vanban.chinhphu.vn/?docid=1",
        attachment_url="https://datafiles.chinhphu.vn/law.pdf",
        question="Trách nhiệm người sử dụng lao động và thời hạn trả lương",
        smart_pages=True,
    )

    assert result["smart_selection_status"] == "probe_match"
    assert result["page_start"] == 13 and result["page_end"] == 17
    assert [page["page"] for page in result["pages"]] == [13, 14, 15, 16, 17]
    assert result["inspected_pages"] == [1, 5, 10, 15, 20, 13, 14, 16, 17]
    assert len(result["inspected_pages"]) <= 10
    assert "trach nhiem nguoi su dung lao dong" in result["text"].casefold()
    assert result["document_sha256"] == __import__("hashlib").sha256(payload).hexdigest()
    assert result["text_sha256"] == result["sha256"]
    assert result["extraction_version"]
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_smart_pdf_uses_matching_outline_and_reports_empty_evidence_honestly():
    from app.services.official_document_reader import extract_official_pdf

    payload = text_pdf(
        [""] * 19 + ["another section"],
        outline=[("Trách nhiệm người sử dụng lao động", 8)],
    )
    result = await extract_official_pdf(
        payload,
        url="https://vanban.chinhphu.vn/?docid=2",
        attachment_url="https://datafiles.chinhphu.vn/law.pdf",
        question="Trách nhiệm người sử dụng lao động",
        smart_pages=True,
    )

    assert result["smart_selection_status"] == "outline_match"
    assert result["page_start"] == 6 and result["page_end"] == 10
    assert result["inspected_pages"] == [6, 7, 8, 9, 10]
    assert len(result["pages"]) <= 5
    assert result["text"] == ""
    assert result["content_status"] == "metadata_only"
    assert result["requires_ocr"] is True


@pytest.mark.parametrize(
    ("question", "expected_status"),
    [
        ("Phí tiếp nhận hồ sơ nộp lúc nào?", "no_evidence_in_probe"),
        ("", "no_question_terms"),
    ],
)
@pytest.mark.asyncio
async def test_smart_pdf_without_outline_handles_unfamiliar_or_empty_question(
    question, expected_status
):
    from app.services.official_document_reader import extract_official_pdf

    result = await extract_official_pdf(
        text_pdf(["Quy định mẫu."] * 12),
        url="https://vanban.chinhphu.vn/?docid=3",
        attachment_url="https://datafiles.chinhphu.vn/law.pdf",
        question=question,
        smart_pages=True,
    )

    assert result["smart_selection_status"] == expected_status
    assert len(result["inspected_pages"]) <= 10


@pytest.mark.asyncio
async def test_default_pdf_window_and_text_hash_semantics_remain_unchanged():
    from app.services.official_document_reader import extract_official_pdf

    result = await extract_official_pdf(
        text_pdf(["one", "two", "three", "four", "five", "six"]),
        url="https://datafiles.chinhphu.vn/law.pdf",
        attachment_url="https://datafiles.chinhphu.vn/law.pdf",
        page_start=3,
        page_limit=2,
    )

    assert result["page_start"] == 3 and result["page_end"] == 4
    assert [page["page"] for page in result["pages"]] == [3, 4]
    assert result["truncated"] is True
    assert result["sha256"] == __import__("hashlib").sha256(
        result["text"].encode()
    ).hexdigest()


@pytest.mark.asyncio
async def test_smart_pdf_worker_is_killed_and_reaped_on_cancellation(monkeypatch):
    import asyncio
    from app.services import official_document_reader as reader

    class Worker:
        returncode = None

        def __init__(self):
            self.started = asyncio.Event()
            self.finished = asyncio.Event()
            self.killed = False
            self.reaped = False

        async def communicate(self, input=None):
            self.started.set()
            await self.finished.wait()
            self.reaped = True
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.finished.set()

        async def wait(self):
            return self.returncode

    worker = Worker()

    async def spawn(*_args, **_kwargs):
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        reader._extract_smart_isolated(
            b"%PDF-test", question="quy định", use_ocr=False, page_limit=5
        )
    )
    await asyncio.wait_for(worker.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.killed is True
    assert worker.reaped is True


@pytest.mark.asyncio
async def test_smart_pdf_worker_timeout_is_typed_and_kills_child(monkeypatch):
    import asyncio
    from app.services import official_document_reader as reader
    from app.services.trusted_source_reader import SourceReadError

    class Worker:
        returncode = None

        def __init__(self):
            self.started = asyncio.Event()
            self.finished = asyncio.Event()
            self.killed = False
            self.reaped = False

        async def communicate(self, input=None):
            self.started.set()
            await self.finished.wait()
            self.reaped = True
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.finished.set()

        async def wait(self):
            return self.returncode

    worker = Worker()

    async def spawn(*_args, **_kwargs):
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(reader, "SMART_WORKER_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(SourceReadError, match="source_processing_timeout"):
        await reader._extract_smart_isolated(
            b"%PDF-test", question="quy định", use_ocr=False, page_limit=5
        )
    assert worker.killed is True
    assert worker.reaped is True


@pytest.mark.asyncio
async def test_smart_pdf_worker_preserves_cancellation_during_timeout_cleanup(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.services import official_document_reader as reader

    class Worker:
        pid = 123
        returncode = None

        def __init__(self):
            self.communicating = asyncio.Event()
            self.finished = asyncio.Event()
            self.wait_started = asyncio.Event()
            self.wait_release = asyncio.Event()
            self.killed = False

        async def communicate(self, input=None):
            self.communicating.set()
            await self.finished.wait()
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.finished.set()

        async def wait(self):
            self.wait_started.set()
            await self.wait_release.wait()
            return self.returncode

    worker = Worker()
    job = object()
    closed_jobs = []

    async def spawn(*_args, **_kwargs):
        return worker

    monkeypatch.setattr(reader, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(reader, "subprocess", SimpleNamespace(CREATE_NO_WINDOW=0))
    monkeypatch.setattr(reader, "_create_windows_worker_job", lambda _process: job)
    monkeypatch.setattr(reader, "_terminate_windows_worker_job", lambda _job: None)
    monkeypatch.setattr(reader, "_close_windows_worker_job", closed_jobs.append)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(reader, "SMART_WORKER_TIMEOUT_SECONDS", 0.01)
    task = asyncio.create_task(
        reader._extract_smart_isolated(
            b"%PDF-test", question="quy định", use_ocr=False, page_limit=5
        )
    )
    await asyncio.wait_for(worker.wait_started.wait(), timeout=1)
    task.cancel()
    worker.wait_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.killed is True
    assert closed_jobs == [job]


@pytest.mark.asyncio
async def test_smart_pdf_worker_preserves_cancellation_during_job_assignment_cleanup(
    monkeypatch,
):
    import asyncio
    from types import SimpleNamespace
    from app.services import official_document_reader as reader

    class Worker:
        pid = 123
        returncode = None

        def __init__(self):
            self.cleanup_started = asyncio.Event()
            self.killed = False
            self.cleanup_cancelled = False

        async def communicate(self, input=None):
            self.cleanup_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cleanup_cancelled = True
                raise

        def kill(self):
            self.killed = True
            self.returncode = -9

    worker = Worker()

    async def spawn(*_args, **_kwargs):
        return worker

    def fail_job_assignment(_process):
        raise OSError("job assignment unavailable")

    monkeypatch.setattr(reader, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(reader, "subprocess", SimpleNamespace(CREATE_NO_WINDOW=0))
    monkeypatch.setattr(reader, "_create_windows_worker_job", fail_job_assignment)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        reader._extract_smart_isolated(
            b"%PDF-test", question="quy định", use_ocr=False, page_limit=5
        )
    )
    await asyncio.wait_for(worker.cleanup_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.killed is True
    assert worker.cleanup_cancelled is True


@pytest.mark.asyncio
@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows process trees only")
async def test_windows_worker_cleanup_kills_owned_descendant_holding_pipe(tmp_path):
    import asyncio
    import ctypes
    import sys
    from pathlib import Path
    from app.services.official_document_reader import (
        _close_windows_worker_job,
        _create_windows_worker_job,
        _kill_and_reap,
        _terminate_windows_worker_job,
    )

    child_pid_file = tmp_path / "owned-child.pid"
    base_python = getattr(sys, "_base_executable", sys.executable)
    parent_code = (
        "import sys; sys.stdin.buffer.read(1); "
        "import subprocess,time; "
        f"child=subprocess.Popen([{base_python!r},'-I','-S','-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(child.pid)); "
        "time.sleep(60)"
    )
    process = await asyncio.create_subprocess_exec(
        base_python,
        "-I",
        "-S",
        "-c",
        parent_code,
        str(child_pid_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        job = _create_windows_worker_job(process)
    except OSError:
        process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)
        raise
    communication = asyncio.create_task(process.communicate(input=b"\0"))
    child_pid = None
    child_handle = None

    async def wait_for_child_pid():
        deadline = asyncio.get_running_loop().time() + 3
        while asyncio.get_running_loop().time() < deadline:
            if child_pid_file.exists():
                return int(Path(child_pid_file).read_text())
            await asyncio.sleep(0.01)
        raise AssertionError("owned child did not start")

    def pid_is_running(pid):
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(handle)

    try:
        child_pid = await wait_for_child_pid()
        child_handle = ctypes.windll.kernel32.OpenProcess(
            0x00100000, False, child_pid
        )  # SYNCHRONIZE; retain identity through termination.
        assert child_handle
        assert pid_is_running(child_pid)
        await asyncio.wait_for(
            _kill_and_reap(process, communication, job), timeout=4
        )
        assert communication.done()
        assert ctypes.windll.kernel32.WaitForSingleObject(child_handle, 3_000) == 0
    finally:
        if child_handle:
            ctypes.windll.kernel32.CloseHandle(child_handle)
        try:
            _terminate_windows_worker_job(job)
        except OSError:
            pass
        _close_windows_worker_job(job)
        if not communication.done():
            await asyncio.wait_for(communication, timeout=3)


@pytest.mark.asyncio
@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows process trees only")
async def test_windows_worker_cleanup_kills_descendant_after_parent_exits(tmp_path):
    import asyncio
    import ctypes
    import sys
    from pathlib import Path
    from app.services.official_document_reader import (
        _close_windows_worker_job,
        _create_windows_worker_job,
        _kill_and_reap,
        _terminate_windows_worker_job,
    )

    child_pid_file = tmp_path / "owned-exited-parent-child.pid"
    base_python = getattr(sys, "_base_executable", sys.executable)
    parent_code = (
        "import sys; sys.stdin.buffer.read(1); "
        "import subprocess; "
        f"child=subprocess.Popen([{base_python!r},'-I','-S','-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(child.pid))"
    )
    process = await asyncio.create_subprocess_exec(
        base_python,
        "-I",
        "-S",
        "-c",
        parent_code,
        str(child_pid_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        job = _create_windows_worker_job(process)
    except OSError:
        process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)
        raise
    parent_handle = ctypes.windll.kernel32.OpenProcess(
        0x00100000, False, process.pid
    )  # SYNCHRONIZE; retained to avoid PID reuse during the assertion.
    assert parent_handle
    communication = asyncio.create_task(process.communicate(input=b"\0"))
    child_pid = None
    child_handle = None

    async def wait_for_child_pid():
        deadline = asyncio.get_running_loop().time() + 3
        while asyncio.get_running_loop().time() < deadline:
            if child_pid_file.exists():
                return int(Path(child_pid_file).read_text())
            await asyncio.sleep(0.01)
        raise AssertionError("owned child did not start")

    def pid_is_running(pid):
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        child_pid = await wait_for_child_pid()
        child_handle = ctypes.windll.kernel32.OpenProcess(
            0x00100000, False, child_pid
        )  # SYNCHRONIZE; retain identity through termination.
        assert child_handle
        assert ctypes.windll.kernel32.WaitForSingleObject(parent_handle, 3_000) == 0
        assert pid_is_running(child_pid)
        await asyncio.wait_for(
            _kill_and_reap(process, communication, job), timeout=3
        )
        assert communication.done()
        assert ctypes.windll.kernel32.WaitForSingleObject(child_handle, 3_000) == 0
    finally:
        if child_handle:
            ctypes.windll.kernel32.CloseHandle(child_handle)
        ctypes.windll.kernel32.CloseHandle(parent_handle)
        try:
            _terminate_windows_worker_job(job)
        except OSError:
            pass
        _close_windows_worker_job(job)
        if not communication.done():
            await asyncio.wait_for(communication, timeout=3)


@pytest.mark.asyncio
async def test_smart_pdf_worker_frames_full_official_pdf_cap_without_base64(monkeypatch):
    import asyncio
    import hashlib
    import json
    import struct
    from app.services import official_document_reader as reader

    class Worker:
        returncode = 0

        async def communicate(self, input=None):
            metadata_size = struct.unpack("!I", input[:4])[0]
            metadata_end = 4 + metadata_size
            metadata = json.loads(input[4:metadata_end])
            payload = input[metadata_end:]
            self.metadata = metadata
            self.payload_size = len(payload)
            self.payload_sha256 = hashlib.sha256(payload).hexdigest()
            response = {
                "page_count": 1,
                "pages": [{"page": 1, "text": ""}],
                "parser_recovered": False,
                "inspected_pages": [1],
                "smart_selection_status": "no_question_terms",
                "ocr_input_length": 0,
            }
            header = json.dumps(response, separators=(",", ":")).encode()
            return struct.pack("!I", len(header)) + header, b""

    worker = Worker()

    async def spawn(*_args, **_kwargs):
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    payload = b"%PDF-" + b"x" * (reader.PDF_MAX_BYTES - 5)
    result = await reader._extract_smart_isolated(
        payload, question="quy định", use_ocr=False, page_limit=5
    )

    assert worker.payload_size == reader.PDF_MAX_BYTES
    assert worker.payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert worker.metadata["payload_length"] == reader.PDF_MAX_BYTES
    assert "payload_base64" not in worker.metadata
    assert result["page_count"] == 1
