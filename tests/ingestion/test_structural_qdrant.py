from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from qdrant_client import models

from app.config import Settings
from app.ingestion.structural_index import StructuralRecord


def _contract():
    module = importlib.import_module("app.ingestion.structural_qdrant")
    return module.StructuralQdrantContract.from_settings(
        Settings(_env_file=None)
    )


def _record(*, issuing_authority: str | None = None) -> StructuralRecord:
    return StructuralRecord(
        record_id="00000000-0000-0000-0000-000000000001",
        body="Điều 1. Phạm vi điều chỉnh.",
        document_id=72_273,
        document_number="30/2001/QH10",
        title="Luật Hải quan",
        source_url="https://example.invalid/72273",
        legal_type="Luật",
        issuing_authority=issuing_authority,
        issuance_date="2001-06-29",
        article="Điều 1",
        clause=None,
        heading_path="Điều 1",
        citation="30/2001/QH10, Điều 1",
        token_count=6,
        dataset_revision="revision-1",
        content_sha256="a" * 64,
        chunk_sha256="b" * 64,
    )


def test_structural_contract_defaults_are_exact_and_frozen() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )

    contract = structural_qdrant.StructuralQdrantContract.from_settings(
        Settings(_env_file=None)
    )

    assert contract.collection_name == "vietlex-legal-rag-v2-pilot"
    assert contract.dense_vector_name == "dense"
    assert contract.sparse_vector_name == "bm25"
    assert contract.dense_model == "Qwen/Qwen3-Embedding-0.6B"
    assert contract.sparse_model == "qdrant/bm25"
    assert contract.dense_size == 1024
    assert contract.dense_model_options == {}
    assert contract.sparse_model_options == {}
    with pytest.raises(Exception):
        contract.dense_size = 384
    with pytest.raises(TypeError):
        contract.dense_model_options["dimensions"] = 384


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"STRUCTURAL_COLLECTION_NAME": "vietlex-legal-rag-v1"}, "collection"),
        ({"STRUCTURAL_DENSE_MODEL": "local-model"}, "dense model"),
        ({"STRUCTURAL_VECTOR_SIZE": 384}, "1024"),
        ({"STRUCTURAL_QUERY_INSTRUCTION": " "}, "instruction"),
        ({"STRUCTURAL_QUERY_INSTRUCTION": "different instruction"}, "instruction"),
        ({"STRUCTURAL_UPLOAD_BATCH_MIN": 257}, "batch"),
    ],
)
def test_structural_contract_rejects_configuration_drift(
    override: dict[str, object],
    message: str,
) -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    settings = Settings(_env_file=None, **override)

    with pytest.raises(ValueError, match=message):
        structural_qdrant.StructuralQdrantContract.from_settings(settings)


def test_point_uses_cloud_documents_and_preserves_null_provenance() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    contract = _contract()
    record = _record()

    point = structural_qdrant.point_from_record(record, contract)

    assert point.vector["dense"] == models.Document(
        text=record.body,
        model="Qwen/Qwen3-Embedding-0.6B",
        options={},
    )
    assert point.vector["bm25"] == models.Document(
        text=record.body,
        model="qdrant/bm25",
        options={},
    )
    assert point.payload["issuing_authority"] is None
    assert point.payload["chunk_sha256"] == "b" * 64
    assert "embedding" not in point.payload


def test_dense_query_is_instructed_but_sparse_query_is_raw() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    contract = _contract()

    dense = structural_qdrant.dense_query_document("  Điều 16  ", contract)
    sparse = structural_qdrant.sparse_query_document("  Điều 16  ", contract)

    assert dense == models.Document(
        text=(
            "Instruct: Given a Vietnamese legal question, retrieve relevant "
            "statutory provisions and preserve exact legal references.\n"
            "Query:Điều 16"
        ),
        model="Qwen/Qwen3-Embedding-0.6B",
        options={},
    )
    assert sparse == models.Document(
        text="Điều 16",
        model="qdrant/bm25",
        options={},
    )


class _FakePointsApi:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def upsert_points(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeSearchApi:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _usage_response(*, models_to_tokens: dict[str, int], query=False):
    result = (
        SimpleNamespace(points=[models.ScoredPoint(id=1, version=0, score=0.9)])
        if query
        else SimpleNamespace(status=models.UpdateStatus.COMPLETED)
    )
    return SimpleNamespace(
        status="ok",
        time=0.125,
        result=result,
        usage=SimpleNamespace(
            inference=SimpleNamespace(
                models={
                    model: SimpleNamespace(tokens=tokens)
                    for model, tokens in models_to_tokens.items()
                }
            )
        ),
    )


def _fake_client(*, upsert_response, query_response=None):
    return SimpleNamespace(
        http=SimpleNamespace(
            points_api=_FakePointsApi(upsert_response),
            search_api=_FakeSearchApi(query_response),
        )
    )


def test_raw_upsert_transport_preserves_exact_inference_usage() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    contract = _contract()
    response = _usage_response(
        models_to_tokens={
            contract.dense_model: 41,
            contract.sparse_model: 41,
        }
    )
    client = _fake_client(upsert_response=response)
    transport = structural_qdrant.StructuralQdrantTransport(client, contract)

    receipt = transport.upsert_with_usage(
        [structural_qdrant.point_from_record(_record(), contract)]
    )

    assert receipt.status == "completed"
    assert receipt.elapsed_seconds == 0.125
    assert receipt.model_tokens == {
        "Qwen/Qwen3-Embedding-0.6B": 41,
        "qdrant/bm25": 41,
    }
    call = client.http.points_api.calls[0]
    assert call["collection_name"] == "vietlex-legal-rag-v2-pilot"
    assert call["wait"] is True
    assert isinstance(call["point_insert_operations"], models.PointsList)


def test_raw_query_transport_retains_filter_points_and_dense_usage() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    contract = _contract()
    response = _usage_response(
        models_to_tokens={contract.dense_model: 9},
        query=True,
    )
    client = _fake_client(
        upsert_response=None,
        query_response=response,
    )
    transport = structural_qdrant.StructuralQdrantTransport(client, contract)
    query_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=72_273),
            )
        ]
    )

    points, receipt = transport.query_with_usage(
        document=structural_qdrant.dense_query_document("Điều 1", contract),
        using="dense",
        limit=3,
        query_filter=query_filter,
    )

    assert [point.id for point in points] == [1]
    assert receipt.model_tokens == {contract.dense_model: 9}
    request = client.http.search_api.calls[0]["query_request"]
    assert request.filter == query_filter
    assert request.using == "dense"


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="ok", time=0.1, result=SimpleNamespace(
            status=models.UpdateStatus.COMPLETED), usage=None),
        _usage_response(models_to_tokens={"unexpected/model": 3}),
    ],
)
def test_raw_transport_rejects_missing_or_unexpected_usage(response) -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    contract = _contract()
    transport = structural_qdrant.StructuralQdrantTransport(
        _fake_client(upsert_response=response),
        contract,
    )

    with pytest.raises(structural_qdrant.StructuralProviderError):
        transport.upsert_with_usage(
            [structural_qdrant.point_from_record(_record(), contract)]
        )


def test_inference_usage_receipt_rejects_zero_attempts() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )

    with pytest.raises(ValidationError, match="attempts"):
        structural_qdrant.InferenceUsageReceipt(
            status="completed",
            elapsed_seconds=0.1,
            model_tokens={"qdrant/bm25": 1},
            attempts=0,
        )


def test_inference_usage_receipt_tokens_are_deeply_frozen() -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    receipt = structural_qdrant.InferenceUsageReceipt(
        status="completed",
        elapsed_seconds=0.1,
        model_tokens={"qdrant/bm25": 1},
    )

    with pytest.raises(TypeError):
        receipt.model_tokens["qdrant/bm25"] = 2


def test_structural_client_uses_cloud_inference_and_system_trust(
    monkeypatch,
) -> None:
    structural_qdrant = importlib.import_module(
        "app.ingestion.structural_qdrant"
    )
    captured: dict[str, object] = {}
    sentinel_client = object()
    sentinel_context = object()

    def fake_qdrant_client(**kwargs):
        captured.update(kwargs)
        return sentinel_client

    monkeypatch.setattr(structural_qdrant, "QdrantClient", fake_qdrant_client)
    monkeypatch.setattr(
        structural_qdrant,
        "system_ssl_context",
        lambda: sentinel_context,
    )

    client = structural_qdrant.create_structural_qdrant_client(
        Settings(
            _env_file=None,
            QDRANT_URL="https://qdrant.example.invalid:6333",
            QDRANT_API_KEY="test-key",
        )
    )

    assert client is sentinel_client
    assert captured == {
        "url": "https://qdrant.example.invalid:6333",
        "api_key": "test-key",
        "cloud_inference": True,
        "prefer_grpc": True,
        "timeout": 120.0,
        "verify": sentinel_context,
        "check_compatibility": False,
    }
