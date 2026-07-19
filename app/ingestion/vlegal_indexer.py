import uuid
import requests
import time
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datasets import load_dataset, get_dataset_config_names
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector
from qdrant_client.http.models import Document
from pyvi import ViTokenizer
from app.ingestion.indexer import text_to_sparse_vector
from app.config import get_settings

def run_vlegal_ingestion():
    settings = get_settings()
    
    unique_contexts = set()
    contexts_file = os.path.join(os.path.dirname(__file__), "vlegal_contexts.json")
    
    # Try to load cached contexts first
    if os.path.exists(contexts_file):
        print(f"Loading cached contexts from local file {contexts_file}...")
        try:
            with open(contexts_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                unique_contexts.update(cached_data)
            print(f"Loaded {len(unique_contexts)} contexts from cache.")
        except Exception as e:
            print(f"Error loading cached contexts: {e}. Falling back to Hugging Face...")
            
    if not unique_contexts:
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
        
        possible_cols = ["context", "ground_truth_context", "reference", "doc", "text", "document", "legal_text", "evidence", "content", "court_judgement", "grounding"]
        
        for config in configs:
            print(f"Loading config '{config}'...")
            try:
                dataset = load_dataset("datht/vlegal", config)
                for split_name in dataset.keys():
                    split_data = dataset[split_name]
                    print(f"  Split '{split_name}' has {len(split_data)} rows.")
                    
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
    # Filter out extremely long contexts that cause PyVi and Qdrant Cloud to hang/fail
    filtered_contexts = [ctx for ctx in unique_contexts if len(ctx) <= 5000]
    total_contexts = len(filtered_contexts)
    print(f"Extracted {len(unique_contexts)} unique legal text contexts. Filtered down to {total_contexts} contexts (<= 5000 chars).")
    unique_contexts = filtered_contexts
    
    if total_contexts == 0:
        print("No contexts found to index!")
        return

    # Connect to Qdrant Cloud
    print(f"Connecting to Qdrant Cloud at {settings.QDRANT_URL} (Inference Mode)...")
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        cloud_inference=True,
        timeout=15.0
    )
    
    collection_name = "vietlex_knowledge_base"
    
    # Ensure collection exists and is configured for size=384
    recreate = False
    if qdrant_client.collection_exists(collection_name):
        info = qdrant_client.get_collection(collection_name)
        current_size = info.config.params.vectors.size
        if current_size != 384:
            print(f"Collection '{collection_name}' has size {current_size}. Deleting and recreating with size 384...")
            qdrant_client.delete_collection(collection_name)
            recreate = True
    else:
        recreate = True

    if recreate:
        print(f"Creating collection '{collection_name}' with size 384...")
        from qdrant_client.models import Distance, VectorParams, SparseVectorParams
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            sparse_vectors_config={
                "sparse-text": SparseVectorParams()
            }
        )

    # 1. Calculate UUIDs and check if they already exist in Qdrant in large chunks (size 500)
    print("Checking existing points in Qdrant...")
    all_uuids = [str(uuid.uuid5(uuid.NAMESPACE_DNS, text)) for text in unique_contexts]
    
    existing_ids = set()
    uuid_batch_size = 500
    for i in range(0, len(all_uuids), uuid_batch_size):
        batch_uuids = all_uuids[i:i+uuid_batch_size]
        try:
            existing = qdrant_client.retrieve(
                collection_name=collection_name,
                ids=batch_uuids,
                with_payload=False,
                with_vectors=False
            )
            existing_ids.update(p.id for p in existing)
        except Exception as e:
            print(f"Error checking existing points chunk: {e}")

    print(f"Total unique contexts: {total_contexts}. Existing points in Qdrant: {len(existing_ids)}")
    
    # Filter to get only new contexts
    missing_contexts = []
    for text in unique_contexts:
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, text))
        if point_id not in existing_ids:
            missing_contexts.append(text)
            
    print(f"Need to index {len(missing_contexts)} new contexts.")
    
    if not missing_contexts:
        print("All contexts are already indexed! No new embeddings to fetch.")
        return

    # Embedding generation & Upserting via local/remote LLM Gateway
    base_url = settings.OMNIGATE_BASE_URL.rstrip('/')
    embedding_url = f"{base_url}/v1/embeddings" if not base_url.endswith('/v1') else f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"
    }

    # Ingest in batches of 8 in parallel to prevent timeouts and optimize throughput
    batch_size = 8
    batches = [missing_contexts[idx:idx+batch_size] for idx in range(0, len(missing_contexts), batch_size)]

    def process_batch(batch_idx, batch_texts):
        import sys
        print(f"\n[Batch {batch_idx}] Processing {len(batch_texts)} texts...")
        sys.stdout.flush()
        # 1. Try Qdrant Cloud Inference first
        batch_points = []
        for text in batch_texts:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, text))
            segmented = ViTokenizer.tokenize(text)
            sparse_vec = text_to_sparse_vector(segmented)
            
            batch_points.append(PointStruct(
                id=point_id,
                vector={
                    "": Document(
                        text=text,
                        model="sentence-transformers/all-minilm-l6-v2"
                    ),
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload={"source_text": text}
            ))
            
        print(f"[Batch {batch_idx}] Submitting to Qdrant Cloud...")
        sys.stdout.flush()
        try:
            local_executor = ThreadPoolExecutor(max_workers=1)
            future = local_executor.submit(
                qdrant_client.upsert,
                collection_name=collection_name,
                points=batch_points
            )
            try:
                print(f"[Batch {batch_idx}] Waiting with timeout=15s...")
                sys.stdout.flush()
                future.result(timeout=15.0)
                print(f"[Batch {batch_idx}] Success!")
                sys.stdout.flush()
            finally:
                local_executor.shutdown(wait=False)
            return True
        except Exception as e:
            print(f"[Batch {batch_idx}] Qdrant Cloud Inference failed or timed out: {e}. Falling back to gemini-embedding-2...")
            sys.stdout.flush()

        # 2. Fallback to gemini-embedding-2 via LiteLLM Gateway
        payload = {
            "model": "legal-embedding-model",
            "input": batch_texts
        }
        
        import random
        response = None
        for attempt in range(10):
            try:
                response = requests.post(embedding_url, headers=headers, json=payload, timeout=60.0)
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt == 9:
                        response = None
                        break
                    sleep_time = (attempt * 10) + 10 + random.uniform(1.0, 8.0)
                    time.sleep(sleep_time)
                    continue
                response.raise_for_status()
                break
            except Exception as conn_err:
                print(f"\nConnection attempt {attempt} failed for batch {batch_idx}: {conn_err}")
                if attempt == 9:
                    response = None
                    break
                time.sleep((attempt * 10) + 10 + random.uniform(1.0, 5.0))
                continue
        
        if response is None:
            print(f"\nError fetching fallback embeddings at batch {batch_idx}: Connection failed.")
            return False
            
        try:
            embeddings_data = response.json()["data"]
        except Exception as parse_err:
            print(f"\nError parsing fallback embeddings at batch {batch_idx}: {parse_err}. Response: {response.text}")
            return False
            
        batch_points_fallback = []
        for text, item in zip(batch_texts, embeddings_data):
            vector = item["embedding"][:384]  # Truncate gemini-embedding-2 to 384 dimensions to match collection schema
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, text))
            
            segmented = ViTokenizer.tokenize(text)
            sparse_vec = text_to_sparse_vector(segmented)
            
            batch_points_fallback.append(PointStruct(
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
            
        # Upsert fallback to Qdrant
        try:
            qdrant_client.upsert(
                collection_name=collection_name,
                points=batch_points_fallback
            )
            return True
        except Exception as upsert_err:
            print(f"\nError upserting fallback batch {batch_idx} to Qdrant: {upsert_err}")
            return False

    print(f"Ingesting {len(missing_contexts)} new points in parallel with 3 workers...")
    
    success_count = 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_batch, idx, batch): idx for idx, batch in enumerate(batches)}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Indexing Batches"):
            if future.result():
                success_count += 1
                
    print(f"Successfully finished indexing {success_count}/{len(batches)} batches to Qdrant!")

if __name__ == "__main__":
    run_vlegal_ingestion()

