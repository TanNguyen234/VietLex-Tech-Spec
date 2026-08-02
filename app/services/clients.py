from __future__ import annotations

import httpx
from pinecone import Pinecone
from qdrant_client import QdrantClient

from app.config import get_settings, system_ssl_context
from app.ingestion.qdrant_inference import create_inference_client


_http_client: httpx.AsyncClient | None = None
_pinecone_client: Pinecone | None = None
_pinecone_index: object | None = None
_qdrant_inference_client: QdrantClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            verify=system_ssl_context(),
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=64,
                max_keepalive_connections=32,
            ),
        )
    return _http_client


def get_pinecone_client() -> Pinecone:
    global _pinecone_client
    if _pinecone_client is None:
        settings = get_settings()
        if not settings.pinecone_api_key:
            raise RuntimeError(
                "PIPECONE_API or PINECONE_API_KEY is required."
            )
        _pinecone_client = Pinecone(api_key=settings.pinecone_api_key)
    return _pinecone_client


def get_pinecone_index() -> object:
    global _pinecone_index
    if _pinecone_index is None:
        settings = get_settings()
        _pinecone_index = get_pinecone_client().index(
            settings.PINECONE_INDEX_NAME,
            grpc=True,
        )
    return _pinecone_index


def get_qdrant_inference_client() -> QdrantClient:
    global _qdrant_inference_client
    if _qdrant_inference_client is None:
        _qdrant_inference_client = create_inference_client(get_settings())
    return _qdrant_inference_client


async def close_clients() -> None:
    global _http_client, _pinecone_client, _pinecone_index
    global _qdrant_inference_client
    if _http_client is not None:
        await _http_client.aclose()
    for client in (
        _pinecone_index,
        _pinecone_client,
        _qdrant_inference_client,
    ):
        close = getattr(client, "close", None)
        if callable(close):
            close()
    _http_client = None
    _pinecone_client = None
    _pinecone_index = None
    _qdrant_inference_client = None
