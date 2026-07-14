import logfire
import uuid
import hashlib
import httpx
from typing import List, Dict
from pyvi import ViTokenizer
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct, SparseVector
from app.config import get_settings

settings = get_settings()

def text_to_sparse_vector(text: str) -> Dict[str, List]:
    tokens = text.lower().split()
    tf = {}
    for token in tokens:
        tf[token] = tf.get(token, 0) + 1
        
    indices = []
    values = []
    for token, count in tf.items():
        hash_val = int(hashlib.md5(token.encode('utf-8')).hexdigest(), 16)
        idx = hash_val % 1000000
        indices.append(idx)
        values.append(float(count))
        
    sorted_pairs = sorted(zip(indices, values))
    return {
        "indices": [p[0] for p in sorted_pairs],
        "values": [p[1] for p in sorted_pairs]
    }

@logfire.instrument("Đồng bộ hóa dữ liệu lên Qdrant")
async def index_documents(chunks: List[Dict]):
    logfire.info("Đang bắt đầu lập chỉ mục tài liệu")
    
    qdrant_client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    
    collection_name = "vietlex_knowledge_base"
    
    texts = [chunk["content"] for chunk in chunks]
    
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }
    
    payload = {
        "model": "legal-embedding-model",
        "input": texts
    }
    
    logfire.info("Đang gọi API OmniGate để sinh embeddings...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(embedding_url, headers=headers, json=payload)
        response.raise_for_status()
        embeddings_data = response.json()["data"]
        
    points = []
    for chunk, item in zip(chunks, embeddings_data):
        dense_vector = item["embedding"][:768]
        
        segmented_content = ViTokenizer.tokenize(chunk["content"])
        sparse_vec = text_to_sparse_vector(segmented_content)
        
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["content"]))
        
        points.append(PointStruct(
            id=point_id,
            vector={
                "": dense_vector,
                "sparse-text": SparseVector(
                    indices=sparse_vec["indices"],
                    values=sparse_vec["values"]
                )
            },
            payload={
                "chapter": chunk["chapter"],
                "section": chunk["section"],
                "article": chunk["article"],
                "source_text": chunk["content"]
            }
        ))
        
    logfire.info("Đang upsert {count} points lên Qdrant...", count=len(points))
    await qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )
    
    logfire.info("Đồng bộ hóa lên Qdrant hoàn tất")
