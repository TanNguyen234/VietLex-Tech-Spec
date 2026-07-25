import os
import sys
import gzip
import json
import uuid
import time
import requests
import logfire
from typing import List, Dict
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams, SparseVector
from pyvi import ViTokenizer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.ingestion.indexer import text_to_sparse_vector
from app.ingestion.parser import parse_legal_document_with_context
from app.config import get_settings

def load_gz_json(file_path: str) -> Dict:
    try:
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def run_reindex_bge_m3(data_dir: str, collection_name: str = "vietlex_laws_crawler_kb"):
    settings = get_settings()
    print(f"Scanning directory '{data_dir}' for legal document files...")
    
    gz_files = []
    if os.path.exists(data_dir):
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".gz") or file.endswith(".json"):
                    gz_files.append(os.path.join(root, file))
                    
    print(f"Found {len(gz_files)} document files.")
    if not gz_files:
        print(f"Error: No data files found in '{data_dir}'. Aborting.")
        return

    chunks = []
    for file_path in tqdm(gz_files, desc="Parsing documents with context enrichment"):
        doc_obj = load_gz_json(file_path)
        if not doc_obj:
            continue
            
        full_text = doc_obj.get("full_text", "").strip()
        title = doc_obj.get("title", "").strip()
        url = doc_obj.get("url", "").strip()
        source = doc_obj.get("source", "").strip()
        source_id = str(doc_obj.get("source_id", ""))
        attributes = doc_obj.get("attribute", {})
        
        if not full_text:
            continue
            
        metadata = {
            "title": title,
            "official_number": attributes.get("official_number", [])
        }
        
        doc_chunks = parse_legal_document_with_context(full_text, metadata)
        
        if not doc_chunks:
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            header_prefix = f"[Văn bản: {title} | Số hiệu: {metadata['official_number']}]"
            for idx, para in enumerate(paragraphs):
                doc_chunks.append({
                    "chapter": "Chương chung",
                    "section": "Mục chung",
                    "article": f"Para-{idx+1}",
                    "content": f"{header_prefix}\n{para}"
                })
                
        for chunk in doc_chunks:
            chunk.update({
                "title": title,
                "url": url,
                "source": source,
                "source_id": source_id,
                "official_number": attributes.get("official_number", []),
                "document_type": attributes.get("document_type", []),
                "issuing_body": attributes.get("issuing_body/office/signer", []),
                "effective_date": attributes.get("effective_date", ""),
                "expiry_date": attributes.get("expiry_date", "")
            })
            chunks.append(chunk)

    print(f"\nExtracted {len(chunks)} enriched legal chunks.")

    # Connect to Qdrant Cloud
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=60.0
    )
    
    # Re-create collection with size 1024 (BGE-M3)
    if qdrant_client.collection_exists(collection_name):
        print(f"Deleting old 384-dim collection '{collection_name}'...")
        qdrant_client.delete_collection(collection_name)

    print(f"Creating new Qdrant collection '{collection_name}' with 1024-dim Cosine vectors...")
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        sparse_vectors_config={
            "sparse-text": SparseVectorParams()
        }
    )

    # Batch embedding via Google Cloud Run BGE-M3 API
    url = settings.EMBEDDING_API_URL
    headers = {"Content-Type": "application/json"}
    if settings.EMBEDDING_SERVICE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBEDDING_SERVICE_API_KEY}"

    batch_size = 16
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    print(f"Pushing {len(chunks)} chunks to Qdrant Cloud in {total_batches} batches...")

    indexed_count = 0
    for idx, i in enumerate(range(0, len(chunks), batch_size), 1):
        batch = chunks[i:i+batch_size]
        batch_texts = [c["content"][:2000] for c in batch]
        
        # Call Cloud Run BGE-M3 service with retry
        embeddings = []
        for attempt in range(5):
            try:
                resp = requests.post(url, json={"inputs": batch_texts, "normalize": True}, headers=headers, timeout=60)
                resp.raise_for_status()
                embeddings = resp.json().get("embeddings", [])
                if embeddings:
                    break
            except Exception as e:
                if attempt == 4:
                    print(f"Warning: Batch {idx} Cloud Run Embedding failed: {e}")
                    raise
                time.sleep(2 ** attempt + 1)
        
        batch_points = []
        for chunk, vector in zip(batch, embeddings):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["content"]))
            segmented = ViTokenizer.tokenize(chunk["content"])
            sparse_vec = text_to_sparse_vector(segmented)
            
            payload_data = {
                "chapter": chunk["chapter"],
                "section": chunk["section"],
                "article": chunk["article"],
                "source_text": chunk["content"],
                "title": chunk["title"],
                "url": chunk["url"],
                "source": chunk["source"],
                "source_id": chunk["source_id"],
                "official_number": chunk["official_number"],
                "document_type": chunk["document_type"],
                "issuing_body": chunk["issuing_body"],
                "effective_date": chunk["effective_date"],
                "expiry_date": chunk["expiry_date"]
            }
            
            batch_points.append(PointStruct(
                id=point_id,
                vector={
                    "": vector,
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload=payload_data
            ))
            
        qdrant_client.upsert(collection_name=collection_name, points=batch_points)
        indexed_count += len(batch_points)
        print(f" Batch [{idx}/{total_batches}] - Pushed {len(batch_points)} points (Total: {indexed_count})")

    print(f"\n==================================================")
    print(f"SUCCESSFULLY RE-INDEXED {indexed_count} CHUNKS WITH 1024-DIM BGE-M3!")
    print(f"==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VietLex BGE-M3 1024-dim Reindexer")
    parser.add_argument("data_dir", type=str, nargs="?", default="app/data/raw_data", help="Path to raw laws directory")
    args = parser.parse_args()
    run_reindex_bge_m3(args.data_dir)

