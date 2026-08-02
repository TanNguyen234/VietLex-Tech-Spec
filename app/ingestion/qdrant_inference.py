from __future__ import annotations

import time
from threading import Lock
from typing import Any

from qdrant_client import QdrantClient, models

from app.config import Settings, system_ssl_context


RETIRED_STORAGE_COLLECTIONS = (
    "vietlex_legal_documents_v1",
    "vietlex_semantic_cache",
)

QUERY_POINT_ID = 2**63 - 1
_QUERY_SLOT_LOCK = Lock()
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_transient(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True
    return type(error).__name__ in {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ResponseHandlingException",
        "TimeoutException",
    }


def _retry_qdrant(
    settings: Settings,
    label: str,
    operation: Any,
) -> Any:
    attempts = max(1, settings.QDRANT_INFERENCE_MAX_RETRIES)
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as error:
            if not _is_transient(error) or attempt == attempts:
                raise
            delay = min(
                settings.QDRANT_INFERENCE_RETRY_MAX_SECONDS,
                settings.QDRANT_INFERENCE_RETRY_BASE_SECONDS
                * (2 ** (attempt - 1)),
            )
            print(
                f"Qdrant {label} transient failure; "
                f"retry={attempt}/{attempts} sleep={delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)


def create_inference_client(settings: Settings) -> QdrantClient:
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        cloud_inference=True,
        prefer_grpc=settings.QDRANT_PREFER_GRPC,
        timeout=120,
        verify=system_ssl_context(),
        check_compatibility=False,
    )


def _create_staging_collection(
    client: QdrantClient,
    settings: Settings,
) -> None:
    client.create_collection(
        collection_name=settings.QDRANT_INFERENCE_COLLECTION_NAME,
        vectors_config=models.VectorParams(
            size=settings.DENSE_VECTOR_SIZE,
            distance=models.Distance.COSINE,
            on_disk=True,
        ),
        hnsw_config=models.HnswConfigDiff(m=0),
        optimizers_config=models.OptimizersConfigDiff(
            indexing_threshold=0,
        ),
        on_disk_payload=True,
    )


def reset_inference_staging(
    client: QdrantClient,
    settings: Settings,
    *,
    allow_destructive: bool,
) -> None:
    if not allow_destructive:
        raise RuntimeError(
            "Qdrant storage cleanup requires explicit authorization."
        )
    for collection_name in (
        *RETIRED_STORAGE_COLLECTIONS,
        settings.QDRANT_INFERENCE_COLLECTION_NAME,
    ):
        exists = _retry_qdrant(
            settings,
            f"collection_exists({collection_name})",
            lambda name=collection_name: client.collection_exists(name),
        )
        if exists:
            _retry_qdrant(
                settings,
                f"delete_collection({collection_name})",
                lambda name=collection_name: client.delete_collection(
                    name, timeout=120
                ),
            )
    _retry_qdrant(
        settings,
        "create_staging_collection",
        lambda: _create_staging_collection(client, settings),
    )


def ensure_inference_staging(
    client: QdrantClient,
    settings: Settings,
) -> None:
    exists = _retry_qdrant(
        settings,
        "collection_exists(staging)",
        lambda: client.collection_exists(
            settings.QDRANT_INFERENCE_COLLECTION_NAME
        ),
    )
    if not exists:
        _retry_qdrant(
            settings,
            "create_staging_collection",
            lambda: _create_staging_collection(client, settings),
        )


def extract_dense_vectors(
    client: QdrantClient,
    settings: Settings,
    texts: list[str],
    *,
    slot: int,
) -> list[list[float]]:
    if not texts:
        return []
    base = slot * settings.UPLOAD_BATCH_SIZE
    point_ids = [base + offset for offset in range(len(texts))]

    def infer_batch() -> Any:
        client.upsert(
            collection_name=settings.QDRANT_INFERENCE_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=models.Document(
                        text=text,
                        model=settings.DENSE_INFERENCE_MODEL,
                    ),
                    payload={},
                )
                for point_id, text in zip(point_ids, texts, strict=True)
            ],
            wait=True,
        )
        return client.retrieve(
            collection_name=settings.QDRANT_INFERENCE_COLLECTION_NAME,
            ids=point_ids,
            with_payload=False,
            with_vectors=True,
        )

    records = _retry_qdrant(
        settings,
        f"embed_batch(slot={slot})",
        infer_batch,
    )
    vectors_by_id: dict[int, list[float]] = {}
    for record in records:
        raw_id = getattr(record.id, "num", record.id)
        vector = record.vector
        if isinstance(vector, dict):
            vector = next(iter(vector.values()), None)
        if not isinstance(vector, list):
            raise RuntimeError("Qdrant inference did not return a dense vector.")
        vectors_by_id[int(raw_id)] = [float(value) for value in vector]
    if set(vectors_by_id) != set(point_ids):
        raise RuntimeError("Qdrant inference returned an incomplete batch.")
    return [vectors_by_id[point_id] for point_id in point_ids]


def embed_query(
    client: QdrantClient,
    settings: Settings,
    text: str,
) -> list[float]:

    def infer_query() -> Any:
        client.upsert(
            collection_name=settings.QDRANT_INFERENCE_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=QUERY_POINT_ID,
                    vector=models.Document(
                        text=text,
                        model=settings.DENSE_INFERENCE_MODEL,
                    ),
                    payload={},
                )
            ],
            wait=True,
        )
        return client.retrieve(
            collection_name=settings.QDRANT_INFERENCE_COLLECTION_NAME,
            ids=[QUERY_POINT_ID],
            with_payload=False,
            with_vectors=True,
        )

    # A fixed serialized slot prevents leaked runtime UUID points from growing
    # the staging collection while preserving query/vector correctness.
    with _QUERY_SLOT_LOCK:
        records = _retry_qdrant(
            settings,
            "embed_query",
            infer_query,
        )
    if len(records) != 1:
        raise RuntimeError("Qdrant query embedding is unavailable.")
    vector: Any = records[0].vector
    if isinstance(vector, dict):
        vector = next(iter(vector.values()), None)
    if not isinstance(vector, list):
        raise RuntimeError("Qdrant query embedding has invalid shape.")
    return [float(value) for value in vector]
