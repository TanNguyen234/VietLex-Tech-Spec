"""Regression tests for the repository's advertised Python floor."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_application_imports_without_typing_self() -> None:
    """Python 3.10 does not expose ``typing.Self``."""
    compatibility_probe = textwrap.dedent(
        """
        import builtins

        original_import = builtins.__import__

        def python_310_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "typing" and "Self" in (fromlist or ()):
                raise ImportError("cannot import name 'Self' from 'typing'")
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = python_310_import

        import app.ingestion.structural_pilot
        import app.ingestion.structural_qdrant
        import app.ingestion.structural_upload
        import app.services.structural_retrieval
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", compatibility_probe],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
