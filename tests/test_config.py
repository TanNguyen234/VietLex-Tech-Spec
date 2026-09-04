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
    assert settings.LLM_MAX_OUTPUT_TOKENS == 1536
    assert settings.QDRANT_RERANK_MODEL == (
        "answerdotai/answerai-colbert-small-v1"
    )
    assert settings.QDRANT_RERANK_VECTOR_SIZE == 96
    assert settings.PINECONE_RERANK_MODEL == "bge-reranker-v2-m3"
    assert settings.CONTENT_STORE_PATH == Path(
        "data/huggingface/content_store.sqlite3"
    )
    assert settings.V3_CONTENT_STORE_PATH == Path(
        "data/v3/content_store.sqlite3"
    )
    assert settings.V3_LEGAL_FTS_PATH == Path(
        "data/v3/legal_fts.sqlite3"
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
        "EMAIL_USER",
        "EMAIL_PASS",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    )

    for secret_name in secret_names:
        assert Settings.model_fields[secret_name].default is None


def test_account_email_defaults_are_minimal_and_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.ACCOUNT_EMAIL_ENABLED is False
    assert settings.EMAIL_USER is None
    assert settings.EMAIL_PASS is None
    assert settings.EMAIL_FROM is None
    assert settings.SMTP_HOST == "smtp.gmail.com"
    assert settings.SMTP_PORT == 587
    assert settings.PUBLIC_BASE_URL == "http://localhost:8000"
    assert settings.AUTH_COOKIE_NAME == "vietlex_auth"
    assert settings.AUTH_SESSION_DAYS == 30


def test_supabase_defaults_are_optional_for_full_doc_export() -> None:
    settings = Settings(_env_file=None)

    assert settings.SUPABASE_URL is None
    assert settings.SUPABASE_PUBLISHABLE_KEY is None
    assert settings.SUPABASE_SERVICE_ROLE_KEY is None


def test_production_web_configuration_fails_closed() -> None:
    import pytest

    from app.config import validate_production_settings

    with pytest.raises(RuntimeError, match="WEB_SESSION_SECRET"):
        validate_production_settings(
            Settings(
                _env_file=None,
                APP_ENV="production",
                FRONTEND_URL="https://vietlex.example",
            )
        )

    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        validate_production_settings(
            Settings(
                _env_file=None,
                APP_ENV="production",
                WEB_SESSION_SECRET="x" * 32,
                FRONTEND_URL="http://localhost:8000",
            )
        )

    with pytest.raises(RuntimeError, match="EMAIL_PASS"):
        validate_production_settings(
            Settings(
                _env_file=None,
                APP_ENV="production",
                WEB_SESSION_SECRET="x" * 32,
                FRONTEND_URL="https://vietlex.example",
                PUBLIC_BASE_URL="https://vietlex.example",
                ACCOUNT_EMAIL_ENABLED=True,
                EMAIL_USER="mailer@example.com",
                EMAIL_FROM="mailer@example.com",
            )
        )

    validate_production_settings(
        Settings(
            _env_file=None,
            APP_ENV="production",
            WEB_SESSION_SECRET="x" * 32,
            FRONTEND_URL="https://vietlex.example",
            PUBLIC_BASE_URL="https://vietlex.example",
            ACCOUNT_EMAIL_ENABLED=True,
            EMAIL_USER="mailer@example.com",
            EMAIL_PASS="secret",
            EMAIL_FROM="mailer@example.com",
        )
    )


def test_legacy_admin_basic_is_off_and_requires_complete_credentials() -> None:
    import pytest

    from app.config import validate_production_settings

    defaults = Settings(_env_file=None)
    assert defaults.LEGACY_ADMIN_BASIC_ENABLED is False
    with pytest.raises(RuntimeError, match="ADMIN_USERNAME"):
        validate_production_settings(
            Settings(
                _env_file=None,
                APP_ENV="production",
                WEB_SESSION_SECRET="x" * 32,
                FRONTEND_URL="https://vietlex.example",
                LEGACY_ADMIN_BASIC_ENABLED=True,
            )
        )


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
    assert settings.STRUCTURAL_PER_DOCUMENT_LIMIT == 8
    assert settings.STRUCTURAL_RERANKER_MODE == "pinecone-only"
    assert settings.STRUCTURAL_RERANK_INPUT_LIMIT == 64
    assert settings.STRUCTURAL_RERANK_RETURN_LIMIT == 6
    assert settings.STRUCTURAL_FINAL_EVIDENCE_LIMIT == 5
    assert settings.STRUCTURAL_CONTEXT_MAX_TOKENS == 720
    assert settings.STRUCTURAL_CONTEXT_PER_DOCUMENT_LIMIT == 2
    assert settings.STRUCTURAL_UPLOAD_BATCH_MIN == 64
    assert settings.STRUCTURAL_UPLOAD_BATCH_MAX == 256


def test_ragas_evaluation_mode_default_is_off() -> None:
    settings = Settings(_env_file=None)
    assert settings.RAGAS_EVALUATION_MODE == "off"
    assert settings.RAGAS_SAMPLE_RATE == 0.1


def test_public_web_features_default_to_safe_off() -> None:
    settings = Settings(_env_file=None)

    assert settings.PUBLIC_NEMO_DEFAULT_ENABLED is False
    assert settings.PUBLIC_RAGAS_ENABLED is False
    assert settings.PUBLIC_RAGAS_CLIENT_DAILY_LIMIT == 3
    assert settings.PUBLIC_RAGAS_GLOBAL_DAILY_LIMIT == 20
    assert settings.CHAT_RATE_LIMIT == "6/minute"
    assert settings.PUBLIC_EVALUATION_RATE_LIMIT == "6/minute"
    assert settings.PUBLIC_PROGRESS_RATE_LIMIT == "180/minute"


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


def test_vertex_defaults_are_narrow_and_do_not_model_adc_credentials() -> None:
    settings = Settings(_env_file=None)

    assert settings.USE_LEGACY_FREE_PIPELINE is False
    assert settings.GOOGLE_CLOUD_PROJECT is None
    assert settings.GOOGLE_CLOUD_LOCATION == "global"
    assert settings.VERTEX_LLM_MODEL == "gemini-3.5-flash"
    assert settings.VERTEX_EMBEDDING_MODEL == "gemini-embedding-2"
    assert settings.VERTEX_QDRANT_COLLECTION_NAME == (
        "vietlex-legal-rag-v3-vertex-1024"
    )
    assert settings.VERTEX_QDRANT_VECTOR_SIZE == 1024
    assert settings.VERTEX_QDRANT_MAX_CHUNKS_PER_DOCUMENT == 16
    assert settings.VERTEX_REQUEST_TIMEOUT_SECONDS == 30.0
    assert settings.VERTEX_MAX_RETRIES == 2
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in Settings.model_fields
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" not in Settings.model_fields


def test_legacy_free_pipeline_switch_is_boolean() -> None:
    import pytest
    from pydantic import ValidationError

    assert (
        Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE=True)
        .USE_LEGACY_FREE_PIPELINE
        is True
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, USE_LEGACY_FREE_PIPELINE="unknown")
