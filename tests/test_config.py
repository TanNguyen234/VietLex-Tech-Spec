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
        "EMBEDDING_SERVICE_API_KEY",
        "LITELLM_MASTER_KEY",
        "COHERE_API_KEY",
        "MONGO_URL",
    )

    for secret_name in secret_names:
        assert Settings.model_fields[secret_name].default is None
