import logfire
import httpx
import uuid
import asyncio
from typing import Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from app.config import get_settings

settings = get_settings()

async def get_embedding(text: str) -> list:
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }
    payload = {
        "model": "legal-embedding-model",
        "input": [text]
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(embedding_url, headers=headers, json=payload)
        response.raise_for_status()
        # text-embedding-004 is 768-dimensional
        return response.json()["data"][0]["embedding"][:768]

async def ensure_cache_collection(client: AsyncQdrantClient, name: str):
    recreate = False
    if await client.collection_exists(name):
        info = await client.get_collection(name)
        current_size = info.config.params.vectors.size
        if current_size != 768:
            logfire.info("Semantic cache size is {size}, recreating with size 768", size=current_size)
            await client.delete_collection(name)
            recreate = True
    else:
        recreate = True
        
    if recreate:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE)
        )

@logfire.instrument("Kiểm tra Semantic Cache cho truy vấn: {user_query}")
async def check_semantic_cache(user_query: str) -> Optional[str]:
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        collection_name = "vietlex_semantic_cache"
        
        await ensure_cache_collection(qdrant_client, collection_name)
        
        # Use text-embedding-004 (via get_embedding fallback model group)
        query_vector = await get_embedding(user_query)
        results = await qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=1
        )
        
        if results.points:
            best_hit = results.points[0]
            # Threshold score must be >= 0.96 per AGENTS.md rule 4
            if best_hit.score >= 0.96:
                logfire.info("Semantic cache HIT with score: {score}", score=best_hit.score)
                return best_hit.payload.get("bot_response")
                
        logfire.info("Semantic cache MISS")
        return None
    except Exception as e:
        logfire.error("Error checking semantic cache: {error}", error=str(e))
        return None

@logfire.instrument("Lưu vào Semantic Cache")
async def save_to_semantic_cache(user_query: str, bot_response: str):
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY
        )
        collection_name = "vietlex_semantic_cache"
        
        await ensure_cache_collection(qdrant_client, collection_name)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, user_query))
        
        # Use text-embedding-004 (via get_embedding fallback model group)
        query_vector = await get_embedding(user_query)
        await qdrant_client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=query_vector,
                    payload={
                        "user_query": user_query,
                        "bot_response": bot_response
                    }
                )
            ]
        )
        logfire.info("Successfully saved to semantic cache using text-embedding-004")
    except Exception as e:
        logfire.error("Error saving to semantic cache: {error}", error=str(e))
