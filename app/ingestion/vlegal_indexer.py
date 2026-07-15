import uuid
import requests
import time
from datasets import load_dataset, get_dataset_config_names
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.config import get_settings

def run_vlegal_ingestion():
    settings = get_settings()
    
    print("Fetching configs for 'datht/vlegal'...")
    try:
        configs = get_dataset_config_names("datht/vlegal")
        configs = [c for c in configs if c != "default"]
    except Exception as e:
        print(f"Error fetching configs: {e}")
        # Fallback to known configs of VLegal-Bench
        configs = [f"task_{i}_{j}" for i in range(1, 6) for j in range(1, 6)]
        configs = [c for c in configs if c not in ["task_4_4", "task_4_5", "task_5_5"]]
        
    print(f"Configs to load: {configs}")
    
    unique_contexts = set()
    possible_cols = ["context", "ground_truth_context", "reference", "doc", "text", "document", "legal_text", "evidence", "content", "court_judgement", "grounding"]
    
    for config in configs:
        # Skip default if it has no data or causes issues, let's try to load all
        print(f"Loading config '{config}'...")
        try:
            dataset = load_dataset("datht/vlegal", config)
            for split_name in dataset.keys():
                split_data = dataset[split_name]
                print(f"  Split '{split_name}' has {len(split_data)} rows.")
                
                # Check for columns
                active_col = None
                for col in possible_cols:
                    if col in split_data.column_names:
                        active_col = col
                        break
                
                if active_col:
                    print(f"  Found column '{active_col}' for context.")
                    for row in split_data:
                        val = row.get(active_col)
                        if isinstance(val, list):
                            for v in val:
                                if v and isinstance(v, str):
                                    unique_contexts.add(v.strip())
                        elif isinstance(val, str) and val:
                            unique_contexts.add(val.strip())
                else:
                    print(f"  Columns: {split_data.column_names}. Trying fallback search.")
                    for row in split_data:
                        for k, val in row.items():
                            if "context" in k or "reference" in k or "doc" in k:
                                if isinstance(val, list):
                                    for v in val:
                                        if v and isinstance(v, str):
                                            unique_contexts.add(v.strip())
                                elif isinstance(val, str) and val:
                                    unique_contexts.add(val.strip())
        except Exception as e:
            print(f"  Error loading config '{config}': {e}")
            
    unique_contexts = sorted(list(unique_contexts))
    total_contexts = len(unique_contexts)
    print(f"Extracted {total_contexts} unique legal text contexts from 'datht/vlegal'.")
    
    if total_contexts == 0:
        print("No contexts found to index!")
        return

    # Connect to Qdrant Cloud
    print(f"Connecting to Qdrant Cloud at {settings.QDRANT_URL}...")
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=30.0
    )
    
    collection_name = "vietlex_knowledge_base"
    
    # Ensure collection exists
    if not qdrant_client.collection_exists(collection_name):
        print(f"Collection '{collection_name}' does not exist! Running creation logic...")
        from qdrant_client.models import Distance, VectorParams, SparseVectorParams
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            sparse_vectors_config={
                "sparse-text": SparseVectorParams()
            }
        )

    # Embedding generation & Upserting via OmniGate
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }

    # Ingest in batches of 128 to optimize API latency
    batch_size = 128
    print(f"Ingesting {total_contexts} points to Qdrant...")
    
    for i in tqdm(range(0, total_contexts, batch_size), desc="Ingesting VLegal"):
        batch_texts = unique_contexts[i:i+batch_size]
        
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
        
        try:
            response.raise_for_status()
            embeddings_data = response.json()["data"]
        except Exception as e:
            print(f"Error fetching embeddings at batch {i}: {e}. Response: {response.text if 'response' in locals() else 'None'}")
            continue
        
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

    print("Successfully finished indexing datht/vlegal to Qdrant!")

if __name__ == "__main__":
    run_vlegal_ingestion()
