from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="PowerShell verifier is Windows-local tooling")
def test_focused_verifier_uses_project_venv_and_forwards_pytest_arguments() -> None:
    """Catch ambient-Python use or dropped focused pytest arguments."""

    repository_root = Path(__file__).resolve().parents[1]
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell is not None

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(repository_root / "scripts" / "verify.ps1"),
            "focused",
            "tests/evaluation/test_provenance.py",
            "--collect-only",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert str(repository_root / ".venv" / "Scripts" / "python.exe") in output
    assert "collected" in output
