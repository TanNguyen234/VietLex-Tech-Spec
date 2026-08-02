from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

from app.config import Settings, system_ssl_context


SNAPSHOT_SCHEMA_VERSION = 1
CONTENT_FILES = tuple(
    f"content/data-{index:05d}-of-00011.parquet" for index in range(11)
)
REQUIRED_PATHS = (
    "README.md",
    "metadata/data-00000-of-00001.parquet",
    *CONTENT_FILES,
)
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class SnapshotError(RuntimeError):
    """Base error for pinned dataset snapshot operations."""


class SnapshotIntegrityError(SnapshotError):
    """Raised when downloaded bytes do not match the pinned manifest."""


@dataclass(frozen=True)
class RequiredDatasetFile:
    path: str
    expected_size: int


@dataclass(frozen=True)
class DownloadedFile:
    path: str
    size: int
    sha256: str
    url: str


@dataclass(frozen=True)
class SnapshotManifest:
    repository: str
    revision: str
    completed_at: str
    schema_version: int
    files: tuple[DownloadedFile, ...]

    @classmethod
    def from_json(cls, data: dict[str, object]) -> "SnapshotManifest":
        raw_files = data.get("files")
        if not isinstance(raw_files, list):
            raise SnapshotIntegrityError("Snapshot manifest files must be a list.")
        files = tuple(DownloadedFile(**item) for item in raw_files)
        return cls(
            repository=str(data["repository"]),
            revision=str(data["revision"]),
            completed_at=str(data["completed_at"]),
            schema_version=int(data["schema_version"]),
            files=files,
        )


def snapshot_directory(settings: Settings) -> Path:
    repository_slug = settings.DATASET_REPOSITORY.replace("/", "__")
    return (
        settings.DATASET_ROOT
        / repository_slug
        / settings.DATASET_REVISION
    )


def resolve_url(settings: Settings, relative_path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{settings.DATASET_REPOSITORY}"
        f"/resolve/{settings.DATASET_REVISION}/{relative_path}?download=true"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _part_path(target: Path) -> Path:
    return Path(f"{target}.part")


def _expected_response_size(headers: httpx.Headers) -> int | None:
    for name in ("x-linked-size", "content-length"):
        value = headers.get(name)
        if value and value.isdigit():
            return int(value)
    return None


async def _probe_remote_size(
    client: httpx.AsyncClient,
    url: str,
    relative_path: str,
) -> int:
    response = await client.get(
        url,
        headers={"Range": "bytes=0-1048575"},
    )
    response.raise_for_status()
    content_range = response.headers.get("content-range", "")
    if response.status_code == 206 and "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        if total.isdigit() and int(total) > 0:
            return int(total)
    if (
        response.status_code == 200
        and relative_path == "README.md"
        and 0 < len(response.content) <= 1024 * 1024
    ):
        return len(response.content)
    raise SnapshotIntegrityError(
        f"Missing remote size for {relative_path}."
    )


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
    return min(60.0, float(2**attempt)) + random.uniform(0.0, 1.0)


async def download_required_file(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    required: RequiredDatasetFile,
    *,
    max_attempts: int = 6,
) -> DownloadedFile:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        actual_size = target.stat().st_size
        if actual_size != required.expected_size:
            raise SnapshotIntegrityError(
                f"Existing file size mismatch for {required.path}: "
                f"expected {required.expected_size}, got {actual_size}."
            )
        return DownloadedFile(
            path=required.path,
            size=actual_size,
            sha256=sha256_file(target),
            url=url,
        )

    part_path = _part_path(target)
    for attempt in range(max_attempts):
        resume_from = part_path.stat().st_size if part_path.exists() else 0
        if resume_from > required.expected_size:
            raise SnapshotIntegrityError(
                f"Partial file size exceeds expected size for {required.path}."
            )
        headers = (
            {"Range": f"bytes={resume_from}-"} if resume_from else {}
        )
        response: httpx.Response | None = None
        try:
            async with client.stream(
                "GET",
                url,
                headers=headers,
            ) as response:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt + 1 >= max_attempts:
                        response.raise_for_status()
                    await asyncio.sleep(_retry_delay(attempt, response))
                    continue

                if resume_from and response.status_code != 206:
                    raise SnapshotIntegrityError(
                        f"Server refused byte-range resume for {required.path}."
                    )
                if not resume_from and response.status_code != 200:
                    response.raise_for_status()

                if resume_from:
                    content_range = response.headers.get("content-range", "")
                    expected_prefix = f"bytes {resume_from}-"
                    if not content_range.startswith(expected_prefix):
                        raise SnapshotIntegrityError(
                            f"Invalid Content-Range for {required.path}: "
                            f"{content_range!r}."
                        )

                mode = "ab" if resume_from else "wb"
                with part_path.open(mode) as handle:
                    async for chunk in response.aiter_bytes(
                        chunk_size=8 * 1024 * 1024
                    ):
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
        except (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.TimeoutException,
        ):
            if attempt + 1 >= max_attempts:
                raise
            await asyncio.sleep(_retry_delay(attempt, response))
            continue

        actual_size = part_path.stat().st_size
        if actual_size != required.expected_size:
            raise SnapshotIntegrityError(
                f"Downloaded file size mismatch for {required.path}: "
                f"expected {required.expected_size}, got {actual_size}."
            )

        digest = sha256_file(part_path)
        os.replace(part_path, target)
        return DownloadedFile(
            path=required.path,
            size=actual_size,
            sha256=digest,
            url=url,
        )

    raise SnapshotError(f"Download attempts exhausted for {required.path}.")


async def resolve_required_files(
    settings: Settings,
    client: httpx.AsyncClient,
    paths: Iterable[str] = REQUIRED_PATHS,
) -> tuple[RequiredDatasetFile, ...]:
    required_files: list[RequiredDatasetFile] = []
    for relative_path in paths:
        response = await client.head(resolve_url(settings, relative_path))
        response.raise_for_status()
        expected_size = _expected_response_size(response.headers)
        if expected_size is None or expected_size <= 0:
            expected_size = await _probe_remote_size(
                client,
                resolve_url(settings, relative_path),
                relative_path,
            )
        required_files.append(
            RequiredDatasetFile(
                path=relative_path,
                expected_size=expected_size,
            )
        )
    return tuple(required_files)


def _write_manifest_atomic(
    directory: Path,
    manifest: SnapshotManifest,
) -> None:
    destination = directory / "manifest.json"
    temporary = Path(f"{destination}.part")
    payload = asdict(manifest)
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def verify_snapshot(
    directory: Path,
    *,
    repository: str,
    revision: str,
    expected_paths: Iterable[str] = REQUIRED_PATHS,
) -> SnapshotManifest:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise SnapshotIntegrityError("Snapshot manifest is missing.")
    manifest = SnapshotManifest.from_json(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    if manifest.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotIntegrityError("Unsupported snapshot schema version.")
    if manifest.repository != repository or manifest.revision != revision:
        raise SnapshotIntegrityError(
            "Snapshot repository or revision does not match configuration."
        )
    expected_set = set(expected_paths)
    actual_set = {item.path for item in manifest.files}
    if actual_set != expected_set:
        raise SnapshotIntegrityError("Snapshot file set is incomplete.")
    for item in manifest.files:
        path = directory / item.path
        if not path.exists():
            raise SnapshotIntegrityError(
                f"Snapshot file is missing: {item.path}."
            )
        if path.stat().st_size != item.size:
            raise SnapshotIntegrityError(
                f"Snapshot size mismatch: {item.path}."
            )
        if sha256_file(path) != item.sha256:
            raise SnapshotIntegrityError(
                f"Snapshot checksum mismatch: {item.path}."
            )
    return manifest


async def download_snapshot(
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> SnapshotManifest:
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        verify=system_ssl_context(),
        follow_redirects=True,
        timeout=httpx.Timeout(120.0),
    )
    try:
        directory = snapshot_directory(settings)
        directory.mkdir(parents=True, exist_ok=True)
        required_files = await resolve_required_files(
            settings,
            active_client,
        )
        missing_bytes = sum(
            item.expected_size
            for item in required_files
            if not (directory / item.path).exists()
        )
        free_bytes = shutil.disk_usage(directory).free
        required_free_bytes = missing_bytes + 1024**3
        if free_bytes < required_free_bytes:
            raise SnapshotError(
                f"Insufficient disk space: need {required_free_bytes} "
                f"bytes, have {free_bytes} bytes."
            )

        downloaded: list[DownloadedFile] = []
        for item in required_files:
            downloaded.append(
                await download_required_file(
                    client=active_client,
                    url=resolve_url(settings, item.path),
                    target=directory / item.path,
                    required=item,
                )
            )

        manifest = SnapshotManifest(
            repository=settings.DATASET_REPOSITORY,
            revision=settings.DATASET_REVISION,
            completed_at=datetime.now(timezone.utc).isoformat(),
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            files=tuple(downloaded),
        )
        _write_manifest_atomic(directory, manifest)
        return verify_snapshot(
            directory,
            repository=settings.DATASET_REPOSITORY,
            revision=settings.DATASET_REVISION,
        )
    finally:
        if owns_client:
            await active_client.aclose()
