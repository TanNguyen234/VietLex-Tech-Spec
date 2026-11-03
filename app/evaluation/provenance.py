from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel


SOURCE_EXCLUDED_PREFIXES = (
    "docs/evaluation/index-pilots/",
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


def is_safe_env_template(path: str) -> bool:
    return PurePosixPath(normalize_git_path(path)).name.casefold() == ".env.example"


def is_sensitive_path(path: str) -> bool:
    normalized = normalize_git_path(path)
    name = PurePosixPath(normalized).name.casefold()
    if is_safe_env_template(normalized):
        return False
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
        ["git", "-c", f"safe.directory={root.as_posix()}", *args],
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


def _is_link_or_reparse_point(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_attribute)


def _hash_git_path(root: Path, relative: str) -> tuple[str, str] | None:
    """Hash a Git path without following any symlink or reparse-point target."""
    normalized = normalize_git_path(relative)
    parts = PurePosixPath(normalized).parts
    path = root
    metadata: os.stat_result | None = None

    for index, part in enumerate(parts):
        path /= part
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            # Git can list tracked paths that are deleted in the working tree.
            return None
        if _is_link_or_reparse_point(metadata):
            target = os.readlink(path)
            target_bytes = target if isinstance(target, bytes) else os.fsencode(target)
            digest = hashlib.sha256(b"link\0" + target_bytes).hexdigest()
            return "/".join(parts[: index + 1]), digest
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return None

    if metadata is None or not stat.S_ISREG(metadata.st_mode):
        return None
    digest = hashlib.sha256(b"file\0")
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return normalized, digest.hexdigest()


def _hash_paths(root: Path, paths: list[str]) -> bytes:
    hashes: dict[str, str] = {}
    for relative in sorted(paths):
        result = _hash_git_path(root, relative)
        if result is not None:
            path, digest = result
            hashes[path] = digest
    lines = [f"{path}:{hashes[path]}" for path in sorted(hashes)]
    return "\n".join(lines).encode("utf-8")


def _hash_untracked(root: Path, paths: list[str]) -> bytes:
    return _hash_paths(root, paths)


def _hash_repository_sources(root: Path) -> bytes:
    raw_paths = _run_git(
        root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    paths = [
        value.decode("utf-8", errors="replace")
        for value in raw_paths.split(b"\0")
        if value
    ]
    source_paths: list[str] = []
    for relative in sorted(paths):
        normalized = normalize_git_path(relative)
        if is_source_excluded(normalized):
            continue
        source_paths.append(relative)
    return _hash_paths(root, source_paths)


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
        safe_env_template_diff_paths: list[str] = []
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
                continue
            if is_safe_env_template(path):
                safe_env_template_diff_paths.append(path)
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
        safe_env_template_diff = (
            _run_git(
                root,
                "diff",
                "--binary",
                "HEAD",
                "--",
                *safe_env_template_diff_paths,
            )
            if safe_env_template_diff_paths
            else b""
        )
        full_payload = b"\n".join(
            [
                sha.encode(),
                full_diff,
                safe_env_template_diff,
                _hash_untracked(root, safe_untracked_paths),
            ]
        )
        source_payload = _hash_repository_sources(root)
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
