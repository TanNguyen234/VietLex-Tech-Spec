import uuid
import requests
import time
from datasets import load_dataset
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams, SparseVector
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.config import get_settings

def run_ingestion():
    settings = get_settings()
    
    # 1. Load dataset and extract unique contexts
    print("Loading dataset 'NamSyntax/Vietnamese-Legal-QA-RAG'...")
    dataset = load_dataset("NamSyntax/Vietnamese-Legal-QA-RAG", split="train")
    
    contexts = []
    for row in dataset:
        gt_context = row.get("ground_truth_context", [])
        if isinstance(gt_context, list):
            contexts.extend(gt_context)
        elif isinstance(gt_context, str):
            contexts.append(gt_context)
            
    unique_contexts = sorted(list(set(contexts)))
    print(f"Extracted {len(unique_contexts)} unique legal text chunks.")

    # 2. Connect to Qdrant Cloud
    print(f"Connecting to Qdrant Cloud at {settings.QDRANT_URL}...")
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30.0
    )
    
    collection_name = "vietlex_knowledge_base"
    
    # Recreate collection to test cleanly
    if qdrant_client.collection_exists(collection_name):
        print(f"Collection '{collection_name}' already exists. Recreating...")
        qdrant_client.delete_collection(collection_name)

    print(f"Creating collection '{collection_name}' with vector size 768 and sparse vector configuration...")
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        sparse_vectors_config={
            "sparse-text": SparseVectorParams()
        }
    )

    # 3. Embedding generation & Upserting via OmniGate
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }

    # ponytail: batch size 16 to balance speed and api limits
    batch_size = 16
    print("Generating embeddings and upserting points...")
    for i in tqdm(range(0, len(unique_contexts), batch_size), desc="Ingesting to Qdrant"):
        batch_texts = unique_contexts[i:i+batch_size]
        
        # Get embeddings
        payload = {
            "model": "legal-embedding-model",
            "input": batch_texts
        }
        # Get embeddings with exponential backoff on 429
        for attempt in range(6):
            response = requests.post(embedding_url, headers=headers, json=payload)
            if response.status_code == 429:
                sleep_time = (2 ** attempt) + 2
                time.sleep(sleep_time)
                continue
            break
        response.raise_for_status()
        embeddings_data = response.json()["data"]
        
        # Build Qdrant points
        batch_points = []
        for text, item in zip(batch_texts, embeddings_data):
            vector = item["embedding"][:768]
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, text))
            
            segmented = ViTokenizer.tokenize(text)
            sparse_vec = text_to_sparse_vector(segmented)
            
            batch_points.append(PointStruct(
                id=point_id,
                vector={
                    "": vector,
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload={"source_text": text}
            ))
        
        # Upsert to Qdrant
        qdrant_client.upsert(
            collection_name=collection_name,
            points=batch_points
        )

    print("Successfully finished indexing to Qdrant!")

if __name__ == "__main__":
    run_ingestion()
