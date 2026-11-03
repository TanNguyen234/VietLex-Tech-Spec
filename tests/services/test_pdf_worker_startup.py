import subprocess
import sys
from pathlib import Path


def test_official_pdf_worker_starts_without_network_or_workspace_schema_imports():
    root = Path(__file__).resolve().parents[2]
    code = """
import site, sys
site.addsitedir(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import app.services.official_pdf_worker
from app.services.official_document_reader import SMART_WORKER_TIMEOUT_SECONDS
unneeded = [name for name in ('httpx', 'pydantic', 'app.services.workspace_documents')
            if name in sys.modules]
assert not unneeded, f'PDF worker imports unrelated dependencies: {unneeded}'
assert SMART_WORKER_TIMEOUT_SECONDS == 15
"""
    result = subprocess.run(
        [getattr(sys, "_base_executable", sys.executable), "-I", "-S", "-c", code,
         str(Path(sys.prefix) / ("Lib/site-packages" if sys.platform == "win32"
                                else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")),
         str(root)],
        capture_output=True, text=True, timeout=30, cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
