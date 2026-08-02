from types import SimpleNamespace

from app.config import Settings
from app.ingestion.qdrant_inference import (
    QUERY_POINT_ID,
    embed_query,
    extract_dense_vectors,
)


def test_staging_slots_return_vectors_in_requested_order() -> None:
    calls: list[dict] = []

    class Client:
        def upsert(self, **kwargs):
            calls.append(kwargs)

        def retrieve(self, **kwargs):
            assert kwargs["ids"] == [256, 257]
            return [
                SimpleNamespace(id=257, vector=[0.0, 2.0]),
                SimpleNamespace(id=256, vector=[1.0, 0.0]),
            ]

    settings = Settings(
        _env_file=None,
        DENSE_VECTOR_SIZE=2,
        UPLOAD_BATCH_SIZE=128,
    )
    vectors = extract_dense_vectors(
        Client(),
        settings,
        ["văn bản một", "văn bản hai"],
        slot=2,
    )

    assert vectors == [[1.0, 0.0], [0.0, 2.0]]
    assert calls[0]["points"][0].id == 256
    assert calls[0]["points"][0].vector.model == settings.DENSE_INFERENCE_MODEL


def test_query_embedding_reuses_one_bounded_staging_slot() -> None:
    calls: list[dict] = []

    class Client:
        def upsert(self, **kwargs):
            calls.append(kwargs)

        def retrieve(self, **kwargs):
            assert kwargs["ids"] == [QUERY_POINT_ID]
            return [SimpleNamespace(id=QUERY_POINT_ID, vector=[1.0, 0.0])]

    settings = Settings(_env_file=None, DENSE_VECTOR_SIZE=2)

    assert embed_query(Client(), settings, "truy vấn") == [1.0, 0.0]
    point = calls[0]["points"][0]
    assert point.id == QUERY_POINT_ID
    assert point.vector.model == settings.DENSE_INFERENCE_MODEL
