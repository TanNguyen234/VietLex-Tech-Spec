import os
import sys
import gzip
import json
import uuid
import time
import logfire
from typing import List, Dict
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams, SparseVector
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.ingestion.parser import parse_legal_document
from app.config import get_settings

# Configure Cache Paths to Drive D to avoid full C: drive (0GB free)
os.environ["FASTEMBED_CACHE_PATH"] = "D:\\Download\\fastembed_cache"
os.environ["HF_HOME"] = "D:\\Download\\hf_cache"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

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
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logfire.error("Failed to read file: {file}, error: {err}", file=file_path, err=str(e))
            return {}

def run_crawler_ingestion(data_dir: str, collection_name: str = "vietlex_laws_crawler_kb"):
    """
    Scans the specified directory for crawled .gz files, chunks the documents,
    generates embeddings via Qdrant FastEmbed (multilingual-MiniLM), and upserts to Qdrant.
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
        
        # Fallback: if regex parser yields nothing, chunk by paragraphs
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
    print(f"\nTotal chunks extracted: {len(chunks)}")
    if not chunks:
        print("No valid chunks extracted from documents.")
        return

    # 3. Initialize FastEmbed Multilingual Local Model (384 dimensions)
    print("\nLoading Qdrant FastEmbed Local Model (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)...")
    from fastembed import TextEmbedding
    embed_model = TextEmbedding(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir="D:\\Download\\fastembed_cache"
    )
    print("FastEmbed local ONNX model initialized successfully!")

    # 4. Connect to Qdrant Cloud
    logfire.info("Connecting to Qdrant Cloud at {url}...", url=settings.QDRANT_URL)
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30.0
    )
    
    # 5. Recreate/initialize collection with 384 vector dimensions
    if qdrant_client.collection_exists(collection_name):
        logfire.info("Collection '{col}' already exists. Recreating...", col=collection_name)
        qdrant_client.delete_collection(collection_name)

    logfire.info("Creating new collection '{col}' with vector size 384...", col=collection_name)
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        sparse_vectors_config={
            "sparse-text": SparseVectorParams()
        }
    )

    # 6. Fast Local Embedding Generation & Batch Upsert
    batch_size = 64
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    print(f"\nStarting FastEmbed Indexing: {len(chunks)} chunks across {total_batches} batches (batch_size={batch_size})...")

    total_indexed = 0

    for idx, i in enumerate(range(0, len(chunks), batch_size), 1):
        batch_chunks = chunks[i:i+batch_size]
        batch_texts = [
            (c.get("content") or "").strip()[:1500] if (c.get("content") or "").strip() else "Nội dung văn bản luật"
            for c in batch_chunks
        ]
        
        # Generate embeddings locally via FastEmbed ONNX
        batch_embeddings = list(embed_model.embed(batch_texts))
        
        # Build Qdrant points
        batch_points = []
        for chunk, vector in zip(batch_chunks, batch_embeddings):
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
                    "": vector.tolist() if hasattr(vector, "tolist") else list(vector),
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload=payload_data
            ))
            
        # Upsert batch to Qdrant Cloud with retries
        upsert_ok = False
        for upsert_attempt in range(6):
            try:
                qdrant_client.upsert(
                    collection_name=collection_name,
                    points=batch_points
                )
                upsert_ok = True
                break
            except Exception as e:
                if upsert_attempt == 5:
                    print(f"   [Batch {idx}/{total_batches} Qdrant Error] Upsert failed: {e}")
                    break
                time.sleep((2 ** upsert_attempt) + 2)

        if upsert_ok:
            total_indexed += len(batch_points)
            print(f" - [Batch {idx}/{total_batches}] Indexed {len(batch_points)} points. Total Qdrant points: {total_indexed}/{len(chunks)}")

    print(f"\n==================================================")
    print(f"FastEmbed Indexing completed successfully for collection '{collection_name}'!")
    print(f"Total points indexed: {total_indexed}")
    print(f"==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vietlex FastEmbed Legal Data Qdrant Indexer")
    parser.add_argument("data_dir", type=str, help="Path to raw data directory")
    parser.add_argument("--collection", type=str, default="vietlex_laws_crawler_kb", help="Qdrant collection name")
    
    args = parser.parse_args()
    run_crawler_ingestion(args.data_dir, args.collection)
