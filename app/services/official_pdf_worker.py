"""Killable, resource-limited process for smart official PDF inspection."""

import json
import struct
import sys

from app.services.document_worker import _limit_memory
from app.services.official_document_reader import PDF_MAX_BYTES, _smart_window
from app.services.runtime_errors import SourceReadError

_MAX_METADATA_BYTES = 16_384


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def main():
    batch = None
    try:
        _limit_memory()
        stdin = sys.stdin.buffer
        size_header = _read_exact(stdin, 4)
        if len(size_header) != 4:
            raise SourceReadError("source_processing_request_invalid")
        metadata_size = struct.unpack("!I", size_header)[0]
        if not 1 <= metadata_size <= _MAX_METADATA_BYTES:
            raise SourceReadError("source_processing_request_invalid")
        metadata = json.loads(_read_exact(stdin, metadata_size))
        payload_size = metadata.get("payload_length")
        if (
            not isinstance(payload_size, int)
            or isinstance(payload_size, bool)
            or not 1 <= payload_size <= PDF_MAX_BYTES
        ):
            raise SourceReadError("source_pdf_body_invalid")
        payload = _read_exact(stdin, payload_size)
        if len(payload) != payload_size or stdin.read(1):
            raise SourceReadError("source_pdf_body_invalid")
        question = metadata.get("question", "")
        page_limit = metadata.get("page_limit", 5)
        use_ocr = metadata.get("use_ocr", False)
        deep_read = metadata.get("deep_read", False)
        if not isinstance(deep_read, bool) or (deep_read and use_ocr):
            raise SourceReadError("source_deep_read_mode_invalid")
        if not isinstance(question, str) or not isinstance(use_ocr, bool):
            raise SourceReadError("source_processing_request_invalid")
        if (
            not isinstance(page_limit, int)
            or isinstance(page_limit, bool)
            or not 1 <= page_limit <= (20 if deep_read else 5)
        ):
            raise SourceReadError("source_page_window_invalid")
        response, batch = _smart_window(payload, question, use_ocr, page_limit, deep_read=deep_read)
    except SourceReadError as error:
        response = {"error": error.kind}
    except Exception:
        response = {"error": "source_processing_unavailable"}
    response["ocr_input_length"] = len(batch or b"")
    header = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    sys.stdout.buffer.write(struct.pack("!I", len(header)))
    sys.stdout.buffer.write(header)
    if batch:
        sys.stdout.buffer.write(batch)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
