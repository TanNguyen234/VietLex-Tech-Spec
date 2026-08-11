from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from functools import lru_cache
from pathlib import Path
import ssl
import threading

import truststore


_SYSTEM_TRUST_INSTALLED = False
_SYSTEM_TRUST_LOCK = threading.Lock()

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:8000"
    
    # Qdrant staging remains the v1 inference path; the structural durable
    # pilot is opt-in and does not change the Pinecone v1 production default.
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_INFERENCE_COLLECTION_NAME: str = "vietlex-embedding-staging"
    QDRANT_RERANK_COLLECTION_NAME: str = "vietlex-rerank-staging"
    QDRANT_RERANK_MODEL: str = "answerdotai/answerai-colbert-small-v1"
    QDRANT_RERANK_VECTOR_NAME: str = "colbert"
    QDRANT_RERANK_VECTOR_SIZE: int = 96
    QDRANT_RERANK_TIMEOUT_SECONDS: float = 12.0
    QDRANT_RERANK_MAX_RETRIES: int = 2
    QDRANT_RERANK_RETRY_BASE_SECONDS: float = 0.25
    QDRANT_RERANK_RETRY_MAX_SECONDS: float = 1.0
    QDRANT_RERANK_STALE_SECONDS: int = 120
    QDRANT_RERANK_CLEANUP_INTERVAL_SECONDS: int = 30
    QDRANT_RERANK_MAX_STAGING_POINTS: int = 256

    # Opt-in Qdrant structural pilot.
    STRUCTURAL_BACKEND_ENABLED: bool = False
    STRUCTURAL_COLLECTION_NAME: str = "vietlex-legal-rag-v2-pilot"
    STRUCTURAL_DENSE_VECTOR_NAME: str = "dense"
    STRUCTURAL_SPARSE_VECTOR_NAME: str = "bm25"
    STRUCTURAL_DENSE_MODEL: str = "Qwen/Qwen3-Embedding-0.6B"
    STRUCTURAL_DENSE_MODEL_OPTIONS: dict[str, object] = Field(
        default_factory=dict
    )
    STRUCTURAL_SPARSE_MODEL: str = "qdrant/bm25"
    STRUCTURAL_SPARSE_MODEL_OPTIONS: dict[str, object] = Field(
        default_factory=dict
    )
    STRUCTURAL_VECTOR_SIZE: int = 1024
    STRUCTURAL_DOCUMENT_TEXT_VERSION: str = "vietlex-structural-document-v2"
    STRUCTURAL_QUERY_INSTRUCTION_VERSION: str = (
        "vietlex-vn-legal-retrieval-v1"
    )
    STRUCTURAL_QUERY_INSTRUCTION: str = (
        "Given a Vietnamese legal question, retrieve relevant statutory "
        "provisions and preserve exact legal references."
    )
    STRUCTURAL_CHUNK_MAX_TOKENS: int = 420
    STRUCTURAL_CHUNK_OVERLAP_TOKENS: int = 48
    STRUCTURAL_DENSE_TOP_K: int = 48
    STRUCTURAL_BM25_TOP_K: int = 48
    STRUCTURAL_FUSED_LIMIT: int = 64
    STRUCTURAL_RRF_K: int = 60
    STRUCTURAL_PER_DOCUMENT_LIMIT: int = 4
    STRUCTURAL_QDRANT_TIMEOUT_SECONDS: float = 120.0
    STRUCTURAL_QDRANT_MAX_RETRIES: int = 5
    STRUCTURAL_QDRANT_RETRY_BASE_SECONDS: float = 1.0
    STRUCTURAL_QDRANT_RETRY_MAX_SECONDS: float = 30.0
    STRUCTURAL_UPLOAD_BATCH_MIN: int = 64
    STRUCTURAL_UPLOAD_BATCH_MAX: int = 256
    STRUCTURAL_UPLOAD_MAX_WORKERS: int = 4
    STRUCTURAL_UPLOAD_PREFER_GRPC: bool = True

    # Pinecone vector storage. PIPECONE_API is retained because the existing
    # deployment secret uses that spelling; PINECONE_API_KEY is also accepted.
    PIPECONE_API: Optional[str] = None
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: str = "vietlex-legal-rag-v1"
    PINECONE_NAMESPACE: str = "legal-documents-v1"
    PINECONE_CACHE_NAMESPACE: str = "semantic-cache-v1"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"
    PINECONE_RERANK_MODEL: str = "bge-reranker-v2-m3"
    PINECONE_RERANK_TIMEOUT_SECONDS: float = 12.0
    HYBRID_EMBEDDING_TIMEOUT_SECONDS: float = 20.0
    HYBRID_QUERY_TIMEOUT_SECONDS: float = 8.0
    HYBRID_MAX_RETRIES: int = 2
    HYBRID_RETRY_BASE_SECONDS: float = 0.25
    HYBRID_RETRY_MAX_SECONDS: float = 1.0
    
    # LLM Gateway (OmniGate)
    OMNIGATE_BASE_URL: str = "https://llmgateway.onrender.com"
    LITELLM_MASTER_KEY: Optional[str] = None
    
    # Direct APIs (Gemini, Groq, OpenRouter, Nvidia NIM)
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    NVIDIA_API_KEY: Optional[str] = None
    
    # Logfire Token
    LOGFIRE_TOKEN: Optional[str] = None
    
    # MongoDB Connection URL
    MONGO_URL: Optional[str] = None

    # Pinned external legal corpus
    DATASET_REPOSITORY: str = "vohuutridung/vietnamese-legal-documents"
    DATASET_REVISION: str = "4d4e10b201544e8a4c49a1d3fa496595a7d486d0"
    EXPECTED_DOCUMENT_COUNT: int = 518_255
    DATASET_ROOT: Path = Path("data/huggingface")
    CONTENT_STORE_PATH: Path = Path("data/huggingface/content_store.sqlite3")
    INGESTION_STATE_PATH: Path = Path("data/huggingface/ingestion_state.sqlite3")
    INGESTION_REPORT_PATH: Path = Path("data/huggingface/ingestion_report.json")
    PINECONE_INGESTION_STATE_PATH: Path = Path(
        "data/huggingface/pinecone_ingestion_state.sqlite3"
    )
    PINECONE_INGESTION_REPORT_PATH: Path = Path(
        "data/huggingface/pinecone_ingestion_report.json"
    )
    LEGAL_FTS_PATH: Path = Path("data/huggingface/legal_fts.sqlite3")
    LEGAL_FTS_RESULT_LIMIT: int = 12

    # Capacity-bounded Pinecone schema and ingestion tuning
    DENSE_INFERENCE_MODEL: str = "intfloat/multilingual-e5-small"
    DENSE_VECTOR_SIZE: int = 384
    DENSE_EMBEDDING_BACKEND: str = "qdrant"
    QDRANT_INFERENCE_CONCURRENCY: int = 8
    QDRANT_PREFER_GRPC: bool = False
    QDRANT_INFERENCE_MAX_RETRIES: int = 8
    QDRANT_INFERENCE_RETRY_BASE_SECONDS: float = 1.0
    QDRANT_INFERENCE_RETRY_MAX_SECONDS: float = 30.0
    UPLOAD_BATCH_SIZE: int = 128
    INGESTION_BATCH_CONCURRENCY: int = 16
    PINECONE_HYBRID_ALPHA: float = 0.75
    PINECONE_SPARSE_MAX_NONZERO: int = 64

    # Runtime two-stage retrieval
    RETRIEVAL_DOCUMENT_LIMIT: int = 24
    RESOLVED_DOCUMENT_LIMIT: int = 16
    QUERY_CHUNK_MAX_TOKENS: int = 220
    QUERY_CHUNK_OVERLAP_TOKENS: int = 24
    RERANK_CANDIDATE_LIMIT: int = 12
    RERANK_INPUT_LIMIT: int = 24
    RERANK_PER_DOCUMENT_LIMIT: int = 4
    LOCAL_CHUNKS_PER_DOCUMENT: int = 4
    RERANK_RETURN_LIMIT: int = 6
    FINAL_EVIDENCE_LIMIT: int = 3
    RERANK_MIN_SCORE: float = 0.05
    RERANK_TOP_K: int = 3
    RERANK_CIRCUIT_BREAKER_FAILURES: int = 2
    RERANK_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 30.0
    LLM_CONTEXT_MAX_TOKENS: int = 720
    LLM_CONTEXT_PER_DOCUMENT_LIMIT: int = 2
    LLM_MAX_OUTPUT_TOKENS: int = 640
    QUERY_REWRITE_MAX_CHARACTERS: int = 2_000
    QUERY_REWRITE_MAX_OUTPUT_TOKENS: int = 96
    QUERY_REWRITE_TIMEOUT_SECONDS: float = 8.0
    GUARDRAIL_TIMEOUT_SECONDS: float = 8.0

    # Retained for deployments that still provide the old environment name.
    LEXICAL_CHUNK_LIMIT: int = 64

    @property
    def pinecone_api_key(self) -> Optional[str]:
        return self.PINECONE_API_KEY or self.PIPECONE_API


    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()


def system_ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def system_grpc_root_certificates() -> bytes | None:
    """Return Windows trust roots in the PEM form expected by gRPC."""
    enumerate_certificates = getattr(ssl, "enum_certificates", None)
    if enumerate_certificates is None:
        return None
    pem_certificates: dict[str, None] = {}
    for store_name in ("ROOT", "CA"):
        for certificate, encoding, _trust in enumerate_certificates(store_name):
            if encoding == "x509_asn":
                pem_certificates[ssl.DER_cert_to_PEM_cert(certificate)] = None
    if not pem_certificates:
        return None
    return "".join(pem_certificates).encode("ascii")


def install_system_trust_store() -> None:
    """Make third-party SDKs use the verified Windows trust store."""
    global _SYSTEM_TRUST_INSTALLED
    with _SYSTEM_TRUST_LOCK:
        if _SYSTEM_TRUST_INSTALLED:
            return
        truststore.inject_into_ssl()
        _SYSTEM_TRUST_INSTALLED = True
