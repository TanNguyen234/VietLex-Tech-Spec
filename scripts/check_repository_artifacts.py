from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class ArtifactViolation:
    kind: str
    path: str
    detail: str


_SECRET_PATTERNS = (
    re.compile(
        r"(?im)^(?:export\s+)?[A-Z][A-Z0-9_]*(?:API_KEY|SERVICE_ROLE_KEY|EMAIL_PASS)"
        r"\s*=\s*(?!YOUR_|None|\$\{|<)[^\s#]+"
    ),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{20,}"),
)
_OPERATIONAL_PREFIXES = ("data/huggingface/", "data/migration/", "data/.tmp/", "data/tmp/")


def audit_repository_artifacts(
    root: Path,
    *,
    files: Sequence[Path],
    max_file_bytes: int = 20_000_000,
    max_run_bytes: int = 50_000_000,
) -> list[ArtifactViolation]:
    root = root.resolve()
    violations: list[ArtifactViolation] = []
    run_sizes: dict[str, int] = {}
    for item in files:
        path = item if item.is_absolute() else root / item
        if not path.is_file():
            continue
        relative = path.resolve().relative_to(root).as_posix()
        size = path.stat().st_size
        if size > max_file_bytes:
            violations.append(ArtifactViolation("oversized_file", relative, str(size)))
        if relative.startswith(_OPERATIONAL_PREFIXES):
            violations.append(ArtifactViolation("operational_data", relative, "local runtime data"))
        parts = relative.split("/")
        if parts[:3] == ["docs", "evaluation", "runs"] and len(parts) >= 4:
            run_root = "/".join(parts[:4])
            run_sizes[run_root] = run_sizes.get(run_root, 0) + size
        if size <= 2_000_000:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in _SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    violations.append(
                        ArtifactViolation("secret", relative, f"match at {match.start()}")
                    )
    for run_root, size in sorted(run_sizes.items()):
        if size > max_run_bytes:
            violations.append(ArtifactViolation("oversized_run", run_root, str(size)))
    return violations


def _changed_files(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "HEAD^",
            "HEAD",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root.as_posix()}",
                "diff",
                "--name-only",
                "HEAD",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    return [root / line for line in result.stdout.splitlines() if line]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    violations = audit_repository_artifacts(root, files=_changed_files(root))
    for violation in violations:
        print(f"{violation.kind}: {violation.path} ({violation.detail})")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
