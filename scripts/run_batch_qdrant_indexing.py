import sys
import os

# Ensure UTF-8 output encoding for Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.ingestion.crawler_indexer import run_crawler_ingestion

def main():
    data_dir = os.path.abspath("app/data/raw_data")
    collection_name = "vietlex_laws_crawler_kb"
    print("==================================================")
    print("STARTING BATCH QDRANT HYBRID VECTOR INDEXING")
    print(f"Data Directory: {data_dir}")
    print(f"Target Qdrant Collection: {collection_name}")
    print("==================================================")
    
    run_crawler_ingestion(data_dir=data_dir, collection_name=collection_name)
    
    print("\n==================================================")
    print(f"QDRANT INDEXING COMPLETE: Collection '{collection_name}' updated.")
    print("==================================================")

if __name__ == "__main__":
    main()
