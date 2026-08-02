from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import tempfile
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.ingestion.checkpoint import CheckpointStore
from app.ingestion.content_store import (
    BuildReport,
    ContentStore,
    StoredDocument,
    build_content_store,
)
from app.ingestion.dataset_snapshot import (
    download_snapshot,
    snapshot_directory,
    verify_snapshot,
)
from app.ingestion.legal_text import (
    build_dense_text,
    build_sparse_text,
    deterministic_point_id,
)
from app.ingestion.pinecone_store import (
    FastSparseEncoder,
    build_record,
    create_control_client,
    reset_or_create_index,
    upload_record_batch,
    verify_index,
    wait_for_vector_count,
)
from app.ingestion.qdrant_inference import (
    create_inference_client,
    embed_query,
    ensure_inference_staging,
    extract_dense_vectors,
    reset_inference_staging,
)


TUNING_SAMPLE_SIZE = 256
BENCHMARK_SAMPLE_SIZE = 1_024


@dataclass(frozen=True)
class PreflightResult:
    snapshot_verified: bool
    content_store_verified: bool
    pinecone_configured: bool
    qdrant_inference_configured: bool
    reranker_configured: bool
    joined_count: int


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    documents: int
    seconds: float
    retries: int
    throttles: int
    permanent_failures: int
    configuration: dict[str, int]

    @property
    def documents_per_second(self) -> float:
        return self.documents / max(self.seconds, 1e-9)


@dataclass(frozen=True)
class BatchInput:
    batch_id: int
    document_ids: list[int]
    documents: list[StoredDocument]
    started_at: float


@dataclass(frozen=True)
class PreparedBatch:
    batch_id: int
    document_ids: list[int]
    points: list[dict[str, Any]]
    started_at: float


@dataclass(frozen=True)
class BatchUploadOutcome:
    batch: PreparedBatch
    seconds: float
    error: Exception | None


def select_tuning_candidate(
    candidates: Iterable[BenchmarkResult],
) -> BenchmarkResult:
    eligible = [item for item in candidates if item.permanent_failures == 0]
    if not eligible:
        raise RuntimeError("No zero-failure tuning candidate is available.")
    return max(eligible, key=lambda item: item.documents_per_second)


def assess_benchmark_speedup(speedup: float) -> dict[str, float | bool]:
    if speedup < 1.0:
        raise RuntimeError(
            f"Optimized ingestion is slower than baseline ({speedup:.2f}x)."
        )
    return {"target_speedup": 3.0, "target_met": speedup >= 3.0}


def iter_numbered_batches(
    document_ids: Iterable[int],
    *,
    batch_size: int,
    completed_batch_ids: set[int],
) -> Iterator[tuple[int, list[int]]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    batch: list[int] = []
    batch_id = 0
    for document_id in document_ids:
        batch.append(document_id)
        if len(batch) == batch_size:
            if batch_id not in completed_batch_ids:
                yield batch_id, batch
            batch = []
            batch_id += 1
    if batch and batch_id not in completed_batch_ids:
        yield batch_id, batch


def assert_resume_batch_size(
    *,
    completed_batch_ids: set[int],
    checkpoint_metrics: dict[str, list[float]],
    upload_batch_size: int,
) -> None:
    if not completed_batch_ids:
        return
    recorded = checkpoint_metrics.get("upload_batch_size")
    if not recorded or int(recorded[-1]) != upload_batch_size:
        raise RuntimeError(
            "Checkpoint upload batch size differs from configuration."
        )


def take_document_ids(
    document_ids: Iterable[int],
    *,
    limit: int,
) -> list[int]:
    if limit < 0:
        raise ValueError("limit must be non-negative.")
    return list(islice(document_ids, limit))


def sample_document_ids(
    document_ids: Iterable[int],
    *,
    population_size: int,
    limit: int,
) -> list[int]:
    if population_size <= 0 or limit <= 0:
        raise ValueError("population_size and limit must be positive.")
    if limit > population_size:
        raise ValueError("limit cannot exceed population_size.")
    positions = {index * population_size // limit for index in range(limit)}
    selected: list[int] = []
    for position, document_id in enumerate(document_ids):
        if position in positions:
            selected.append(document_id)
            if len(selected) == limit:
                break
    if len(selected) != limit:
        raise RuntimeError("Corpus ended before deterministic sample completed.")
    return selected


def partition_sparse_texts(
    texts: list[str],
    *,
    workers: int,
) -> list[list[str]]:
    if workers <= 0:
        raise ValueError("workers must be positive.")
    if not texts:
        return []
    chunk_size = max(1, math.ceil(len(texts) / workers))
    return [
        texts[start : start + chunk_size]
        for start in range(0, len(texts), chunk_size)
    ]


def assert_destructive_preflight(result: PreflightResult) -> None:
    checks = {
        "snapshot": result.snapshot_verified,
        "content_store": result.content_store_verified,
        "pinecone": result.pinecone_configured,
        "qdrant_inference": result.qdrant_inference_configured,
        "reranker": result.reranker_configured,
        "joined_count_518255": result.joined_count == 518_255,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Destructive preflight failed: {', '.join(failed)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingestion.hf_pipeline"
    )
    subcommands = parser.add_subparsers(dest="phase", required=True)
    subcommands.add_parser("download")
    subcommands.add_parser("prepare")
    subcommands.add_parser("smoke")
    subcommands.add_parser("benchmark")
    full = subcommands.add_parser("full")
    full.add_argument("--delete-existing", action="store_true")
    full.add_argument("--yes", action="store_true")
    subcommands.add_parser("verify")
    return parser


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(f"{path}.part")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def configure_process_temp(path: Path) -> Path:
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(resolved)
    tempfile.tempdir = str(resolved)
    return resolved


async def run_smoke(settings: Settings) -> PreflightResult:
    verify_snapshot(
        snapshot_directory(settings),
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
    )
    report = ContentStore(settings.CONTENT_STORE_PATH).build_report()
    result = PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        pinecone_configured=bool(settings.pinecone_api_key),
        qdrant_inference_configured=bool(
            settings.QDRANT_URL and settings.QDRANT_API_KEY
        ),
        reranker_configured=bool(settings.RERANK_API_URL),
        joined_count=report.joined_count,
    )
    _write_json_atomic(
        settings.DATASET_ROOT / "preflight_report.json",
        {**result.__dict__, "dataset_revision": settings.DATASET_REVISION},
    )
    return result


async def run_download(settings: Settings) -> dict[str, Any]:
    manifest = await download_snapshot(settings)
    return {
        "repository": manifest.repository,
        "revision": manifest.revision,
        "file_count": len(manifest.files),
        "total_bytes": sum(item.size for item in manifest.files),
    }


def run_prepare(settings: Settings) -> BuildReport:
    snapshot = snapshot_directory(settings)
    verify_snapshot(
        snapshot,
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
    )
    return build_content_store(
        snapshot,
        settings.CONTENT_STORE_PATH,
        expected_count=settings.EXPECTED_DOCUMENT_COUNT,
    )


def _iter_all_document_ids(
    store: ContentStore,
    *,
    page_size: int = 10_000,
) -> Iterator[int]:
    after_id = -1
    while True:
        page = store.iter_document_ids(after_id=after_id, limit=page_size)
        if not page:
            return
        yield from page
        after_id = page[-1]


async def _prepare_batch(
    batch: BatchInput,
    *,
    slot: int,
    settings: Settings,
    qdrant: Any,
    qdrant_semaphore: asyncio.Semaphore,
    sparse_encoder: FastSparseEncoder,
) -> PreparedBatch:
    dense_texts = [
        build_dense_text(
            document.metadata,
            document.content,
            content_is_normalized=True,
        )
        for document in batch.documents
    ]
    sparse_texts = [
        build_sparse_text(
            document.metadata,
            document.content,
            content_is_normalized=True,
        )
        for document in batch.documents
    ]
    async with qdrant_semaphore:
        dense_vectors = await asyncio.to_thread(
            extract_dense_vectors,
            qdrant,
            settings,
            dense_texts,
            slot=slot,
        )
    sparse_vectors = await asyncio.to_thread(
        lambda: [
            sparse_encoder.encode_document(text)
            for text in sparse_texts
        ]
    )
    points = [
        build_record(
            document=document,
            dense_vector=dense,
            sparse_vector=sparse,
            settings=settings,
        )
        for document, dense, sparse in zip(
            batch.documents,
            dense_vectors,
            sparse_vectors,
            strict=True,
        )
    ]
    return PreparedBatch(
        batch_id=batch.batch_id,
        document_ids=batch.document_ids,
        points=points,
        started_at=batch.started_at,
    )


async def upload_prepared_batches(
    *,
    client: Any,
    settings: Any,
    batches: list[PreparedBatch],
    uploader: Any = upload_record_batch,
) -> list[BatchUploadOutcome]:
    async def upload(batch: PreparedBatch) -> BatchUploadOutcome:
        try:
            await asyncio.to_thread(uploader, client, settings, batch.points)
        except Exception as error:
            return BatchUploadOutcome(
                batch=batch,
                seconds=time.perf_counter() - batch.started_at,
                error=error,
            )
        return BatchUploadOutcome(
            batch=batch,
            seconds=time.perf_counter() - batch.started_at,
            error=None,
        )

    return list(await asyncio.gather(*(upload(batch) for batch in batches)))


async def run_benchmark(settings: Settings) -> dict[str, Any]:
    return {
        "remote_requests_executed": 0,
        "reason": "Live benchmark disabled to preserve Pinecone free quota.",
        "configuration": {
            "upload_batch": settings.UPLOAD_BATCH_SIZE,
            "batch_concurrency": settings.INGESTION_BATCH_CONCURRENCY,
            "dense_dimension": settings.DENSE_VECTOR_SIZE,
            "sparse_nonzero": settings.PINECONE_SPARSE_MAX_NONZERO,
        },
    }


async def run_full(
    settings: Settings,
    *,
    allow_destructive: bool,
) -> dict[str, Any]:
    preflight = await run_smoke(settings)
    assert_destructive_preflight(preflight)
    store = ContentStore(settings.CONTENT_STORE_PATH)
    store_report = store.build_report()
    checkpoint = CheckpointStore(
        settings.PINECONE_INGESTION_STATE_PATH,
        revision=settings.DATASET_REVISION,
        secrets=(
            settings.pinecone_api_key,
            settings.QDRANT_API_KEY,
            settings.EMBEDDING_SERVICE_API_KEY,
        ),
    )
    completed = checkpoint.completed_batch_ids()
    metrics = checkpoint.metrics()
    assert_resume_batch_size(
        completed_batch_ids=completed,
        checkpoint_metrics=metrics,
        upload_batch_size=settings.UPLOAD_BATCH_SIZE,
    )
    if not completed:
        checkpoint.record_metric(
            "upload_batch_size", float(settings.UPLOAD_BATCH_SIZE)
        )

    control = create_control_client(settings)
    backend = settings.DENSE_EMBEDDING_BACKEND.casefold()
    if backend != "qdrant":
        control.close()
        raise RuntimeError(
            "DENSE_EMBEDDING_BACKEND must be 'qdrant'."
        )
    qdrant = create_inference_client(settings)
    initialized = bool(metrics.get("pinecone_initialized"))
    if completed and not control.has_index(settings.PINECONE_INDEX_NAME):
        qdrant.close()
        control.close()
        raise RuntimeError(
            "Checkpoint has completed batches but Pinecone index is missing."
        )
    if initialized:
        ensure_inference_staging(qdrant, settings)
    else:
        reset_inference_staging(
            qdrant,
            settings,
            allow_destructive=allow_destructive,
        )
    # Validate the remote model before any destructive Pinecone operation.
    probe = await asyncio.to_thread(
        embed_query,
        qdrant,
        settings,
        "kiểm tra kết nối",
    )
    if len(probe) != settings.DENSE_VECTOR_SIZE:
        qdrant.close()
        control.close()
        raise RuntimeError("Qdrant inference returned the wrong dimension.")
    index, created = reset_or_create_index(
        control,
        settings,
        allow_destructive=allow_destructive,
        resume_existing_target=initialized,
    )
    if not initialized:
        checkpoint.record_metric("pinecone_initialized", 1.0)

    sparse_encoder = FastSparseEncoder(
        average_document_length=store_report.average_sparse_document_length,
        max_nonzero_terms=settings.PINECONE_SPARSE_MAX_NONZERO,
    )
    qdrant_semaphore = asyncio.Semaphore(
        max(1, settings.QDRANT_INFERENCE_CONCURRENCY)
    )
    started = time.perf_counter()
    uploaded_points = 0

    async def flush_window(window: list[BatchInput]) -> None:
        nonlocal uploaded_points
        async def prepare_and_upload(
            slot: int,
            batch: BatchInput,
        ) -> BatchUploadOutcome:
            prepared = await _prepare_batch(
                batch,
                slot=slot,
                settings=settings,
                qdrant=qdrant,
                qdrant_semaphore=qdrant_semaphore,
                sparse_encoder=sparse_encoder,
            )
            return (
                await upload_prepared_batches(
                    client=index,
                    settings=settings,
                    batches=[prepared],
                )
            )[0]

        # Start each Pinecone upsert as soon as its Qdrant embedding batch is
        # ready instead of waiting for the entire 16-batch window.
        outcomes = list(
            await asyncio.gather(
                *(
                    prepare_and_upload(slot, batch)
                    for slot, batch in enumerate(window)
                )
            )
        )
        errors: list[Exception] = []
        window_points = 0
        for outcome in outcomes:
            batch = outcome.batch
            if outcome.error is not None:
                for document_id in batch.document_ids:
                    checkpoint.record_failure(
                        document_id=document_id,
                        stage="pinecone_upload",
                        category=type(outcome.error).__name__,
                        message=str(outcome.error),
                        attempts=1,
                    )
                errors.append(outcome.error)
                continue
            checkpoint.clear_failures(
                document_ids=batch.document_ids,
                stage="pinecone_upload",
            )
            checkpoint.mark_completed(
                batch_id=batch.batch_id,
                first_id=batch.document_ids[0],
                last_id=batch.document_ids[-1],
                point_count=len(batch.points),
                seconds=outcome.seconds,
            )
            window_points += len(batch.points)
            uploaded_points += len(batch.points)
        if outcomes:
            print(
                f"batches={outcomes[0].batch.batch_id}-"
                f"{outcomes[-1].batch.batch_id} points={window_points} "
                f"seconds={max(item.seconds for item in outcomes):.2f}",
                flush=True,
            )
        if errors:
            raise errors[0]

    try:
        window: list[BatchInput] = []
        for batch_id, batch_ids in iter_numbered_batches(
            _iter_all_document_ids(store),
            batch_size=settings.UPLOAD_BATCH_SIZE,
            completed_batch_ids=completed,
        ):
            documents_by_id = store.get_many(batch_ids)
            missing = set(batch_ids) - set(documents_by_id)
            if missing:
                raise RuntimeError(f"Missing local documents: {sorted(missing)}")
            window.append(
                BatchInput(
                    batch_id=batch_id,
                    document_ids=batch_ids,
                    documents=[documents_by_id[item] for item in batch_ids],
                    started_at=time.perf_counter(),
                )
            )
            if len(window) >= settings.INGESTION_BATCH_CONCURRENCY:
                await flush_window(window)
                window = []
        if window:
            await flush_window(window)

        final_count = await asyncio.to_thread(
            wait_for_vector_count,
            index,
            settings,
            expected_count=settings.EXPECTED_DOCUMENT_COUNT,
        )
        failures = checkpoint.failures()
        if failures:
            raise RuntimeError(f"Ingestion has {len(failures)} audited failures.")
        result = {
            "dataset_repository": settings.DATASET_REPOSITORY,
            "dataset_revision": settings.DATASET_REVISION,
            "pinecone_index": settings.PINECONE_INDEX_NAME,
            "pinecone_namespace": settings.PINECONE_NAMESPACE,
            "pinecone_index_created": created,
            "dense_embedding_backend": backend,
            "uploaded_this_run": uploaded_points,
            "final_vector_count": final_count,
            "wall_seconds": time.perf_counter() - started,
            "configuration": {
                "dense_model": settings.DENSE_INFERENCE_MODEL,
                "dense_dimension": settings.DENSE_VECTOR_SIZE,
                "upload_batch": settings.UPLOAD_BATCH_SIZE,
                "batch_concurrency": settings.INGESTION_BATCH_CONCURRENCY,
                "qdrant_inference_concurrency": (
                    settings.QDRANT_INFERENCE_CONCURRENCY
                ),
                "qdrant_staging_point_cap": (
                    settings.INGESTION_BATCH_CONCURRENCY
                    * settings.UPLOAD_BATCH_SIZE
                    + 1
                ),
                "sparse_nonzero": settings.PINECONE_SPARSE_MAX_NONZERO,
            },
            "checkpoint_metrics": checkpoint.metrics(),
        }
        _write_json_atomic(settings.PINECONE_INGESTION_REPORT_PATH, result)
        return result
    finally:
        close = getattr(index, "close", None)
        if callable(close):
            close()
        qdrant.close()
        control.close()


def verify_full(settings: Settings) -> dict[str, Any]:
    manifest = verify_snapshot(
        snapshot_directory(settings),
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
    )
    store = ContentStore(settings.CONTENT_STORE_PATH)
    report = store.build_report()
    control = create_control_client(settings)
    index = control.index(settings.PINECONE_INDEX_NAME, grpc=True)
    try:
        verification = verify_index(
            control,
            index,
            settings,
            expected_count=settings.EXPECTED_DOCUMENT_COUNT,
        )
        document_ids = take_document_ids(_iter_all_document_ids(store), limit=20)
        point_ids = [
            deterministic_point_id(
                settings.DATASET_REPOSITORY,
                settings.DATASET_REVISION,
                document_id,
            )
            for document_id in document_ids
        ]
        response = index.fetch(ids=point_ids, namespace=settings.PINECONE_NAMESPACE)
        vectors = (
            response.get("vectors", {})
            if isinstance(response, dict)
            else getattr(response, "vectors", {})
        )
        if len(vectors) != len(point_ids):
            raise RuntimeError("Pinecone verification fetch is incomplete.")
        documents = store.get_many(document_ids)
        for vector in vectors.values():
            metadata = (
                vector.get("metadata", {})
                if isinstance(vector, dict)
                else getattr(vector, "metadata", {})
            )
            document_id = int(metadata["document_id"])
            if metadata.get("content_sha256") != documents[document_id].content_sha256:
                raise RuntimeError("Pinecone/local content hash mismatch.")
        return {
            "snapshot_files": len(manifest.files),
            "local_joined_count": report.joined_count,
            "remote_vector_count": verification.vector_count,
            "sample_hashes_verified": len(vectors),
        }
    finally:
        close = getattr(index, "close", None)
        if callable(close):
            close()
        control.close()


async def _run_phase(
    arguments: argparse.Namespace,
    settings: Settings,
) -> dict[str, Any]:
    if arguments.phase == "download":
        return await run_download(settings)
    if arguments.phase == "prepare":
        return run_prepare(settings).__dict__
    if arguments.phase == "smoke":
        return (await run_smoke(settings)).__dict__
    if arguments.phase == "benchmark":
        return await run_benchmark(settings)
    if arguments.phase == "full":
        if not arguments.delete_existing or not arguments.yes:
            raise RuntimeError("Full ingestion requires --delete-existing --yes.")
        return await run_full(settings, allow_destructive=True)
    if arguments.phase == "verify":
        return verify_full(settings)
    raise RuntimeError(f"Unsupported phase: {arguments.phase}")


def main() -> None:
    arguments = build_parser().parse_args()
    settings = get_settings()
    configure_process_temp(settings.DATASET_ROOT / ".tmp")
    result = asyncio.run(_run_phase(arguments, settings))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
