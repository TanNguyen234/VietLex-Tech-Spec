import os
import gzip
import json
import uuid
import requests
import time
import logfire
from typing import List, Dict
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams, SparseVector
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.ingestion.parser import parse_legal_document
import sys
from app.config import get_settings

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure Logfire conditionally with local fallback
try:
    logfire.configure(console=False)
except Exception:
    logfire.configure(send_to_logfire=False, console=False)

def load_gz_json(file_path: str) -> Dict:
    """Reads and parses a single gzip-compressed JSON file."""
    try:
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logfire.error("Failed to read gzip file: {file}, error: {err}", file=file_path, err=str(e))
        return {}

def run_crawler_ingestion(data_dir: str, collection_name: str = "vietlex_laws_crawler_kb"):
    """
    Scans the specified directory for crawled .gz files, chunks the documents,
    generates embeddings, and upserts them to Qdrant.
    """
    settings = get_settings()
    
    # 1. Scan for crawled transform files
    logfire.info("Scanning directory {dir} for crawled .gz files...", dir=data_dir)
    gz_files = []
    if os.path.exists(data_dir):
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".gz"):
                    gz_files.append(os.path.join(root, file))
    
    logfire.info("Found {count} crawled files.", count=len(gz_files))
    if not gz_files:
        print(f"No crawled .gz files found in: {data_dir}")
        return

    # 2. Extract and parse chunks from files
    chunks = []
    for file_path in tqdm(gz_files, desc="Parsing legal documents"):
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
            
        # Parse text into Chapter -> Section -> Article
        doc_chunks = parse_legal_document(full_text)
        
        # Fallback: if regex parser yields nothing, chunk by paragraphs or char length
        if not doc_chunks:
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            for idx, para in enumerate(paragraphs):
                doc_chunks.append({
                    "chapter": "Default",
                    "section": "Default",
                    "article": f"Para-{idx+1}",
                    "content": para
                })
        
        # Append metadata to each chunk
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

    logfire.info("Total extracted chunks ready for indexing: {count}", count=len(chunks))
    print(f"Total chunks extracted: {len(chunks)}")
    
    if not chunks:
        print("No valid chunks extracted from documents.")
        return

    # 3. Connect to Qdrant Cloud
    logfire.info("Connecting to Qdrant Cloud at {url}...", url=settings.QDRANT_URL)
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30.0
    )
    
    # 4. Recreate/initialize new collection
    if qdrant_client.collection_exists(collection_name):
        logfire.info("Collection '{col}' already exists. Recreating...", col=collection_name)
        qdrant_client.delete_collection(collection_name)

    logfire.info("Creating new collection '{col}' with vector size 768...", col=collection_name)
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        sparse_vectors_config={
            "sparse-text": SparseVectorParams()
        }
    )

    # 5. Ingestion in Parallel Batches via OmniGate
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }

    batch_size = 16
    chunk_batches = [chunks[i:i+batch_size] for i in range(0, len(chunks), batch_size)]

    def process_batch(batch_tuple):
        batch_idx, batch_chunks = batch_tuple
        batch_texts = [
            (c.get("content") or "").strip()[:3000] if (c.get("content") or "").strip() else "Nội dung văn bản luật"
            for c in batch_chunks
        ]
        
        payload = {
            "model": "legal-embedding-model",
            "input": batch_texts
        }
        
        embeddings_data = None
        for attempt in range(8):
            try:
                response = requests.post(embedding_url, headers=headers, json=payload, timeout=60.0)
                if response.status_code == 429:
                    sleep_sec = (2 ** attempt) + 5
                    time.sleep(sleep_sec)
                    continue
                if response.status_code == 400:
                    payload["input"] = [t[:1500] for t in batch_texts]
                    response = requests.post(embedding_url, headers=headers, json=payload, timeout=60.0)
                response.raise_for_status()
                res_json = response.json()
                if isinstance(res_json, dict) and "data" in res_json:
                    embeddings_data = res_json["data"]
                    break
                else:
                    time.sleep(3)
            except Exception as e:
                if attempt == 7:
                    print(f"\n[Error] Skipping batch {batch_idx} due to embedding error: {e}")
                    return 0
                time.sleep((2 ** attempt) + 3)

        if not embeddings_data:
            return 0
            
        # Build Qdrant points
        batch_points = []
        for chunk, item in zip(batch_chunks, embeddings_data):
            vec = item["embedding"][:768] if isinstance(item, dict) and "embedding" in item else item[:768]
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
                    "": vec,
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload=payload_data
            ))
            
        # Upsert batch to Qdrant with exponential backoff for transient errors
        for upsert_attempt in range(6):
            try:
                qdrant_client.upsert(
                    collection_name=collection_name,
                    points=batch_points
                )
                break
            except Exception as e:
                if upsert_attempt == 5:
                    print(f"\n[Qdrant Error] Failed to upsert batch {batch_idx} after 6 attempts: {e}")
                    return 0
                time.sleep((2 ** upsert_attempt) + 2)

        return len(batch_points)

    total_indexed = 0
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_batch, (idx, b)): idx for idx, b in enumerate(chunk_batches)}
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(chunk_batches), desc="Parallel Indexing Chunks"):
            try:
                count = future.result()
                total_indexed += count
            except Exception as e:
                print(f"\n[Worker Exception]: {e}")

    print(f"\nIndexing completed successfully for collection '{collection_name}'!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vietlex Crawler Data Qdrant Indexer")
    parser.add_argument("data_dir", type=str, help="Path to the directory containing crawled transform .gz files")
    parser.add_argument("--collection", type=str, default="vietlex_laws_crawler_kb", help="Qdrant collection name")
    
    args = parser.parse_args()
    run_crawler_ingestion(args.data_dir, args.collection)
