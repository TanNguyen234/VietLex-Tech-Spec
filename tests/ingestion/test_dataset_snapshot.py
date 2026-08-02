import hashlib
import importlib
from pathlib import Path

import httpx
import pytest

from app.config import Settings


def _snapshot_module():
    return importlib.import_module("app.ingestion.dataset_snapshot")


def test_snapshot_directory_contains_exact_revision(tmp_path: Path) -> None:
    snapshot = _snapshot_module()
    settings = Settings(DATASET_ROOT=tmp_path, _env_file=None)

    assert snapshot.snapshot_directory(settings) == (
        tmp_path
        / "vohuutridung__vietnamese-legal-documents"
        / settings.DATASET_REVISION
    )


@pytest.mark.asyncio
async def test_download_resumes_part_file_and_writes_verified_target(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_module()
    payload = b"0123456789"
    target = tmp_path / "content" / "part.parquet"
    target.parent.mkdir(parents=True)
    part_path = Path(f"{target}.part")
    part_path.write_bytes(payload[:4])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Range"] == "bytes=4-"
        return httpx.Response(
            206,
            content=payload[4:],
            headers={"Content-Range": "bytes 4-9/10"},
        )

    required = snapshot.RequiredDatasetFile(
        path="content/part.parquet",
        expected_size=10,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        downloaded = await snapshot.download_required_file(
            client=client,
            url="https://example.invalid/pinned/content/part.parquet",
            target=target,
            required=required,
        )

    assert target.read_bytes() == payload
    assert not part_path.exists()
    assert downloaded.sha256 == hashlib.sha256(payload).hexdigest()
    assert downloaded.size == 10


@pytest.mark.asyncio
async def test_download_rejects_wrong_final_size(tmp_path: Path) -> None:
    snapshot = _snapshot_module()
    target = tmp_path / "metadata.parquet"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"short")

    required = snapshot.RequiredDatasetFile(
        path="metadata.parquet",
        expected_size=10,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(snapshot.SnapshotIntegrityError, match="size"):
            await snapshot.download_required_file(
                client=client,
                url="https://example.invalid/pinned/metadata.parquet",
                target=target,
                required=required,
            )

    assert not target.exists()


@pytest.mark.asyncio
async def test_dataset_card_size_falls_back_to_bounded_get() -> None:
    snapshot = _snapshot_module()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        assert request.method == "GET"
        assert request.headers["Range"] == "bytes=0-1048575"
        return httpx.Response(200, content=b"dataset card")

    settings = Settings(_env_file=None)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        required = await snapshot.resolve_required_files(
            settings,
            client,
            paths=("README.md",),
        )

    assert required == (
        snapshot.RequiredDatasetFile(
            path="README.md",
            expected_size=12,
        ),
    )
