"""Short-lived document parser with a hard memory ceiling and parent deadline."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from app.services.workspace_documents import (
    DocumentExtractionError,
    ExtractedWorkspaceDocument,
    MAX_UPLOAD_BYTES,
    extract_workspace_document,
)

_MEMORY_BYTES = 256 * 1024 * 1024


def _limit_memory():
    if os.name != 'nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_BYTES, _MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        return None
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64),
                    ('flags', w.DWORD), ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                    ('active', w.DWORD), ('affinity', c.c_size_t),
                    ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class Extended(c.Structure):
        _fields_ = [('basic', Basic), ('io', c.c_uint64 * 6),
                    ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                    ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]

    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.AssignProcessToJobObject.restype = w.BOOL
    job = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.process_memory = _MEMORY_BYTES
    if not job or not kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)):
        raise OSError('memory_limit_unavailable')
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise OSError('memory_limit_unavailable')
    return job  # OS retains this handle until the short-lived process exits.


def extract_isolated(filename: str, media_type: str, payload: bytes):
    if len(payload) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError('document_too_large')
    request = json.dumps({'filename': filename[:180], 'media_type': media_type[:160],
                          'payload': base64.b64encode(payload).decode('ascii')}).encode()
    try:
        completed = subprocess.run(
            [sys.executable, '-m', 'app.services.document_worker'],
            input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parents[2], timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
    except subprocess.TimeoutExpired:
        raise DocumentExtractionError('document_processing_timeout') from None
    except OSError:
        raise DocumentExtractionError('document_processing_unavailable') from None
    if completed.returncode or len(completed.stdout) > 2_000_000:
        raise DocumentExtractionError('document_processing_limit')
    try:
        response = json.loads(completed.stdout)
        if 'error' in response:
            raise DocumentExtractionError(response['error'])
        return ExtractedWorkspaceDocument.model_validate(response)
    except DocumentExtractionError:
        raise
    except (ValueError, TypeError):
        raise DocumentExtractionError('document_processing_failed') from None


def main():
    try:
        job = _limit_memory()
        request = json.loads(sys.stdin.buffer.read(14_000_001))
        payload = base64.b64decode(request['payload'], validate=True)
        result = extract_workspace_document(request['filename'], request['media_type'], payload)
        response = result.model_dump(mode='json')
        del job
    except DocumentExtractionError as error:
        response = {'error': error.kind}
    except Exception:
        response = {'error': 'document_processing_unavailable'}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()
