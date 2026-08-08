from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel


SOURCE_EXCLUDED_PREFIXES = (
    "docs/evaluation/preflight/",
    "docs/evaluation/runs/",
)
SOURCE_EXCLUDED_PATHS = {"docs/evaluation/CURRENT_STATUS.md"}
SOURCE_EXCLUDED_SUFFIXES = (".tmp", ".pyc")
GIT_SENSITIVE_EXCLUDES = (
    ":!.env",
    ":!.env.*",
    ":!**/.env",
    ":!**/.env.*",
    ":!**/credentials.json",
    ":!**/secrets.json",
    ":!**/service-account.json",
    ":!**/*.key",
    ":!**/*.pem",
    ":!**/*.p12",
    ":!**/*.pfx",
)


class GitProvenance(BaseModel):
    status: Literal["ok", "unavailable"]
    error: str | None = None
    repository_root: str
    git_sha: str
    git_dirty: bool
    git_tracked_dirty: bool
    git_staged_dirty: bool
    git_untracked_dirty: bool
    git_diff_sha256: str | None
    git_diff_status: Literal["ok", "clean", "redacted", "unavailable"]
    git_diff_reason: str | None = None
    source_state_sha256: str | None


def normalize_git_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def is_sensitive_path(path: str) -> bool:
    normalized = normalize_git_path(path)
    name = PurePosixPath(normalized).name.casefold()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name
        in {
            "credentials.json",
            "secrets.json",
            "service-account.json",
        }
        or PurePosixPath(name).suffix
        in {
            ".key",
            ".pem",
            ".p12",
            ".pfx",
        }
    )


def is_source_excluded(path: str) -> bool:
    normalized = normalize_git_path(path)
    return (
        is_sensitive_path(normalized)
        or normalized in SOURCE_EXCLUDED_PATHS
        or normalized.startswith(SOURCE_EXCLUDED_PREFIXES)
        or normalized.endswith(SOURCE_EXCLUDED_SUFFIXES)
        or "/__pycache__/" in f"/{normalized}/"
        or normalized.startswith(".pytest_cache/")
    )


def _run_git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode(
            "utf-8", errors="replace"
        ).strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed")
    return completed.stdout


def _hash_untracked(root: Path, paths: list[str]) -> bytes:
    lines: list[str] = []
    for relative in sorted(paths):
        path = root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{normalize_git_path(relative)}:{digest}")
    return "\n".join(lines).encode("utf-8")


def collect_git_provenance(
    repo_root: Path | None = None,
) -> GitProvenance:
    requested_root = Path(repo_root or Path.cwd()).resolve()
    try:
        root = Path(
            _run_git(requested_root, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="replace")
            .strip()
        ).resolve()
        sha = _run_git(root, "rev-parse", "HEAD").decode().strip()
        raw_status = _run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
        )
        entries = [entry for entry in raw_status.split(b"\0") if entry]
        tracked_dirty = False
        staged_dirty = False
        untracked_paths: list[str] = []
        safe_untracked_paths: list[str] = []
        source_untracked_paths: list[str] = []
        sensitive_dirty = False

        for entry in entries:
            text = entry.decode("utf-8", errors="replace")
            code = text[:2]
            path = text[3:]
            if is_sensitive_path(path):
                sensitive_dirty = True
            if code == "??":
                untracked_paths.append(path)
                if not is_sensitive_path(path):
                    safe_untracked_paths.append(path)
                if not is_source_excluded(path):
                    source_untracked_paths.append(path)
                continue
            staged_dirty = staged_dirty or code[0] not in {" ", "?"}
            tracked_dirty = tracked_dirty or code[1] not in {" ", "?"}

        full_diff = _run_git(
            root,
            "diff",
            "--binary",
            "HEAD",
            "--",
            ".",
            *GIT_SENSITIVE_EXCLUDES,
        )
        full_payload = b"\n".join(
            [
                sha.encode(),
                full_diff,
                _hash_untracked(root, safe_untracked_paths),
            ]
        )
        source_diff = _run_git(
            root,
            "diff",
            "--binary",
            "HEAD",
            "--",
            ".",
            ":!docs/evaluation/preflight",
            ":!docs/evaluation/runs",
            ":!docs/evaluation/CURRENT_STATUS.md",
            *GIT_SENSITIVE_EXCLUDES,
        )
        source_payload = b"\n".join(
            [
                sha.encode(),
                source_diff,
                _hash_untracked(root, source_untracked_paths),
            ]
        )
        git_dirty = bool(entries)
        return GitProvenance(
            status="ok",
            repository_root=str(root),
            git_sha=sha,
            git_dirty=git_dirty,
            git_tracked_dirty=tracked_dirty,
            git_staged_dirty=staged_dirty,
            git_untracked_dirty=bool(untracked_paths),
            git_diff_sha256=(
                hashlib.sha256(full_payload).hexdigest()
                if git_dirty and not sensitive_dirty
                else None
            ),
            git_diff_status=(
                "redacted"
                if sensitive_dirty
                else ("ok" if git_dirty else "clean")
            ),
            git_diff_reason=(
                "sensitive_content_not_hashed"
                if sensitive_dirty
                else None
            ),
            source_state_sha256=hashlib.sha256(
                source_payload
            ).hexdigest(),
        )
    except Exception as error:
        return GitProvenance(
            status="unavailable",
            error=f"{type(error).__name__}: {error}",
            repository_root=str(requested_root),
            git_sha="unknown_git_sha",
            git_dirty=False,
            git_tracked_dirty=False,
            git_staged_dirty=False,
            git_untracked_dirty=False,
            git_diff_sha256=None,
            git_diff_status="unavailable",
            git_diff_reason="git_command_failed",
            source_state_sha256=None,
        )
