import os
import sys
import gzip
import json
import uuid
import time
import logfire
from typing import Any, Dict
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.ingestion.parser import parse_legal_document_with_context
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


def preflight_qdrant_collection(
    qdrant_client: QdrantClient,
    collection_name: str,
    expected_vector_size: int,
    expected_sparse_name: str = "sparse-text",
):
    """Read-only collection compatibility check before any write."""
    if not qdrant_client.collection_exists(collection_name):
        raise RuntimeError(
            f"Qdrant collection '{collection_name}' does not exist. "
            "Create/cutover collection outside crawler_indexer scope."
        )

    info = qdrant_client.get_collection(collection_name)
    vector_size = _extract_dense_vector_size(info)
    if vector_size != expected_vector_size:
        raise RuntimeError(
            f"Qdrant collection '{collection_name}' vector size mismatch: "
            f"expected={expected_vector_size}, actual={vector_size}."
        )

    sparse_names = _extract_sparse_vector_names(info)
    if sparse_names and expected_sparse_name not in sparse_names:
        raise RuntimeError(
            f"Qdrant collection '{collection_name}' missing sparse vector '{expected_sparse_name}'. "
            f"available={sorted(sparse_names)}"
        )


def _extract_dense_vector_size(collection_info: Any) -> Any:
    params = getattr(getattr(collection_info, "config", None), "params", None)
    vectors = getattr(params, "vectors", None)
    if isinstance(vectors, dict):
        dense = vectors.get("") or next(iter(vectors.values()), None)
        return getattr(dense, "size", None) if dense is not None else None
    return getattr(vectors, "size", None)


def _extract_sparse_vector_names(collection_info: Any) -> set:
    params = getattr(getattr(collection_info, "config", None), "params", None)
    sparse_vectors = getattr(params, "sparse_vectors", None)
    if sparse_vectors is None:
        sparse_vectors = getattr(params, "sparse_vectors_config", None)
    if isinstance(sparse_vectors, dict):
        return set(sparse_vectors.keys())
    return set()

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
        attributes = doc_obj.get("attribute", {}) or doc_obj.get("attributes", {})
        
        if not full_text:
            continue
            
        metadata = dict(doc_obj)
        metadata["attributes"] = attributes
        metadata.setdefault("raw_schema", doc_obj.get("schema", {}))

        # Parse through integrity-first adapter. Failed/ambiguous documents are
        # intentionally blocked from indexing.
        doc_chunks = parse_legal_document_with_context(full_text, metadata=metadata)
        if not doc_chunks:
            logfire.warning("Document blocked by integrity gate: {source_id}", source_id=source_id)
            continue
        
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

    # 3. Connect to Qdrant Cloud and preflight existing collection.
    logfire.info("Connecting to Qdrant Cloud at {url}...", url=settings.QDRANT_URL)
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30.0
    )
    preflight_qdrant_collection(qdrant_client, collection_name, expected_vector_size=384)

    # 4. Initialize FastEmbed Multilingual Local Model (384 dimensions)
    print("\nLoading Qdrant FastEmbed Local Model (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)...")
    from fastembed import TextEmbedding
    embed_model = TextEmbedding(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir="D:\\Download\\fastembed_cache"
    )
    print("FastEmbed local ONNX model initialized successfully!")

    # 5. Fast Local Embedding Generation & Batch Upsert
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
            point_basis = "|".join([
                str(chunk.get("document_hash") or ""),
                str(chunk.get("chunk_id") or ""),
                str(chunk.get("content") or ""),
            ])
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, point_basis))
            
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
                "expiry_date": chunk["expiry_date"],
                "document_hash": chunk.get("document_hash"),
                "body_hash": chunk.get("body_hash"),
                "audit_id": chunk.get("audit_id"),
                "pipeline_version": chunk.get("pipeline_version"),
                "template_id": chunk.get("template_id"),
                "source_block_ids": chunk.get("source_block_ids", []),
                "node_id": chunk.get("node_id"),
                "node_type": chunk.get("node_type"),
                "body_source": chunk.get("body_source"),
                "candidate_decision": chunk.get("candidate_decision"),
                "disposition": chunk.get("disposition")
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

    print("\n==================================================")
    print(f"FastEmbed Indexing completed successfully for collection '{collection_name}'!")
    print(f"Total points indexed: {total_indexed}")
    print("==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vietlex FastEmbed Legal Data Qdrant Indexer")
    parser.add_argument("data_dir", type=str, help="Path to raw data directory")
    parser.add_argument("--collection", type=str, default="vietlex_laws_crawler_kb", help="Qdrant collection name")
    
    args = parser.parse_args()
    run_crawler_ingestion(args.data_dir, args.collection)
