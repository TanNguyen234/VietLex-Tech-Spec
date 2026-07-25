import asyncio
import sys
import os
import json

sys.path.append("d:/Download/ProfessionalLegalRAG")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from qdrant_client import AsyncQdrantClient
from app.config import get_settings

settings = get_settings()

async def scroll_chunks():
    client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    points, _ = await client.scroll(
        collection_name="vietlex_laws_crawler_kb",
        limit=60,
        with_payload=True,
        with_vectors=False
    )
    await client.close()
    
    extracted = []
    for i, p in enumerate(points):
        text = p.payload.get("source_text", "")
        doc_id = p.payload.get("law_id", f"doc_{i}")
        title = p.payload.get("title", "")
        if text and len(text.strip()) >= 150:
            extracted.append({
                "id": i,
                "doc_id": doc_id,
                "title": title,
                "text": text.strip()
            })
            
    print(f"Successfully scrolled {len(extracted)} valid text chunks from Qdrant.")
    out_dir = os.path.abspath("docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "scrolled_chunks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)
    print(f"Saved scrolled chunks to {out_path}")

if __name__ == "__main__":
    asyncio.run(scroll_chunks())
