from pathlib import Path

from app.config import Settings


def test_migration_defaults_are_pinned_and_capacity_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.DATASET_REPOSITORY == (
        "vohuutridung/vietnamese-legal-documents"
    )
    assert settings.DATASET_REVISION == (
        "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
    )
    assert settings.EXPECTED_DOCUMENT_COUNT == 518_255
    assert settings.DENSE_VECTOR_SIZE == 384
    assert settings.DENSE_INFERENCE_MODEL == "intfloat/multilingual-e5-small"
    assert settings.QDRANT_INFERENCE_COLLECTION_NAME == (
        "vietlex-embedding-staging"
    )
    assert settings.PINECONE_INDEX_NAME == "vietlex-legal-rag-v1"
    assert settings.PINECONE_NAMESPACE == "legal-documents-v1"
    assert settings.UPLOAD_BATCH_SIZE == 128
    assert settings.INGESTION_BATCH_CONCURRENCY == 16
    assert settings.PINECONE_SPARSE_MAX_NONZERO == 64
    assert settings.RETRIEVAL_DOCUMENT_LIMIT == 24
    assert settings.LEXICAL_CHUNK_LIMIT == 64
    assert settings.RERANK_TOP_K == 3
    assert settings.QUERY_CHUNK_MAX_TOKENS == 220
    assert settings.RERANK_CANDIDATE_LIMIT == 12
    assert settings.RERANK_RETURN_LIMIT == 6
    assert settings.LLM_CONTEXT_MAX_TOKENS == 720
    assert settings.QDRANT_RERANK_MODEL == (
        "answerdotai/answerai-colbert-small-v1"
    )
    assert settings.QDRANT_RERANK_VECTOR_SIZE == 96
    assert settings.PINECONE_RERANK_MODEL == "bge-reranker-v2-m3"
    assert settings.CONTENT_STORE_PATH == Path(
        "data/huggingface/content_store.sqlite3"
    )
    assert settings.INGESTION_STATE_PATH == Path(
        "data/huggingface/ingestion_state.sqlite3"
    )
    assert settings.INGESTION_REPORT_PATH == Path(
        "data/huggingface/ingestion_report.json"
    )
    assert settings.PINECONE_INGESTION_STATE_PATH == Path(
        "data/huggingface/pinecone_ingestion_state.sqlite3"
    )


def test_secret_defaults_never_contain_credentials() -> None:
    secret_names = (
        "QDRANT_API_KEY",
        "PIPECONE_API",
        "PINECONE_API_KEY",
        "PINECONE_API",
        "LITELLM_MASTER_KEY",
        "MONGO_URL",
    )

    for secret_name in secret_names:
        assert Settings.model_fields[secret_name].default is None


def test_pinecone_api_compatibility_name_is_resolved() -> None:
    settings = Settings(_env_file=None, PINECONE_API="compat-key")

    assert settings.pinecone_api_key == "compat-key"


def test_qdrant_structural_pilot_defaults_are_exact_and_opt_in() -> None:
    settings = Settings(_env_file=None)

    assert settings.STRUCTURAL_BACKEND_ENABLED is False
    assert settings.STRUCTURAL_COLLECTION_NAME == (
        "vietlex-legal-rag-v2-pilot-384"
    )
    assert settings.STRUCTURAL_DENSE_VECTOR_NAME == "dense"
    assert settings.STRUCTURAL_SPARSE_VECTOR_NAME == "bm25"
    assert settings.STRUCTURAL_DENSE_MODEL == (
        "intfloat/multilingual-e5-small"
    )
    assert (
        settings.STRUCTURAL_DOCUMENT_TEXT_VERSION
        == "vietlex-structural-document-v2"
    )
    assert settings.STRUCTURAL_DENSE_MODEL_OPTIONS == {}
    assert settings.STRUCTURAL_SPARSE_MODEL == "qdrant/bm25"
    assert settings.STRUCTURAL_SPARSE_MODEL_OPTIONS == {}
    assert settings.STRUCTURAL_VECTOR_SIZE == 384
    assert settings.STRUCTURAL_QUERY_INSTRUCTION_VERSION == (
        "vietlex-vn-legal-retrieval-v1"
    )
    assert settings.STRUCTURAL_CHUNK_MAX_TOKENS == 420
    assert settings.STRUCTURAL_CHUNK_OVERLAP_TOKENS == 48
    assert settings.STRUCTURAL_UPLOAD_BATCH_MIN == 64
    assert settings.STRUCTURAL_UPLOAD_BATCH_MAX == 256


def test_ragas_evaluation_mode_default_is_off() -> None:
    settings = Settings(_env_file=None)
    assert settings.RAGAS_EVALUATION_MODE == "off"
    assert settings.RAGAS_SAMPLE_RATE == 0.1


def test_ragas_evaluation_mode_invalid_fails_validation() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, RAGAS_EVALUATION_MODE="invalid_mode")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, RAGAS_SAMPLE_RATE=1.5)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, RAGAS_SAMPLE_RATE=-0.1)


def test_ragas_evaluation_mode_accepted_values() -> None:
    for mode in ("off", "sample", "all"):
        s = Settings(_env_file=None, RAGAS_EVALUATION_MODE=mode)
        assert s.RAGAS_EVALUATION_MODE == mode
