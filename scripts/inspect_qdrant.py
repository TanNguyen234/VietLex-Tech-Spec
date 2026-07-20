import asyncio
import os
import sys

# Ensure UTF-8 output on Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from qdrant_client import AsyncQdrantClient
from app.config import get_settings

async def inspect():
    settings = get_settings()
    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY
    )
    
    collections = await client.get_collections()
    print("Available collections:", [c.name for c in collections.collections])
    
    info = await client.get_collection("vietlex_knowledge_base")
    print(f"vietlex_knowledge_base status: {info.status}")
    print(f"Points count: {info.points_count}")
    print(f"Vectors config: {info.config.params.vectors}")
    
    # Scroll sample points to analyze legal domains / documents
    points, _ = await client.scroll(
        collection_name="vietlex_knowledge_base",
        limit=10,
        with_payload=True,
        with_vectors=False
    )
    
    print(f"\nRetrieved {len(points)} sample points:")
    for idx, pt in enumerate(points):
        source = pt.payload.get("source", "N/A")
        title = pt.payload.get("title", "N/A")
        text = pt.payload.get("source_text", pt.payload.get("text", ""))[:150]
        print(f"[{idx+1}] ID: {pt.id} | Source: {source} | Title: {title}")
        print(f"    Snippet: {text}...\n")
        
    await client.close()

if __name__ == "__main__":
    asyncio.run(inspect())
