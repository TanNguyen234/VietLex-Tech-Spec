import os
import gzip
import json
import pymongo
import logfire
from typing import Dict, List
from tqdm import tqdm
import sys
from app.config import get_settings

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
        # Try normal json if not gzipped
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logfire.error("Failed to read file: {file}, error: {err}", file=file_path, err=str(e))
            return {}

def run_mongo_ingestion(data_dir: str, collection_name: str = "raw_legal_documents", db_name: str = "Legal-RAG"):
    """
    Scans the data_dir for raw document files (.gz or .json) and upserts them
    into the specified MongoDB collection.
    """
    settings = get_settings()
    if not settings.MONGO_URL:
        raise ValueError("MONGO_URL environment variable is not set.")

    logfire.info("Connecting to MongoDB Atlas...")
    client = pymongo.MongoClient(settings.MONGO_URL, serverSelectionTimeoutMS=10000)
    db = client[db_name]
    collection = db[collection_name]

    # Create index on source_id or url for fast lookup & deduplication
    collection.create_index("source_id", unique=True, sparse=True)
    collection.create_index("url", sparse=True)

    logfire.info("Scanning directory {dir} for document files...", dir=data_dir)
    files_to_process = []
    if os.path.exists(data_dir):
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".gz") or (file.endswith(".json") and not file.startswith("sample_")):
                    files_to_process.append(os.path.join(root, file))

    logfire.info("Found {count} raw document files.", count=len(files_to_process))
    if not files_to_process:
        print(f"No document files found in: {data_dir}")
        return

    upserted_count = 0
    updated_count = 0

    for file_path in tqdm(files_to_process, desc="Pushing raw docs to MongoDB"):
        doc_obj = load_gz_json(file_path)
        if not doc_obj:
            continue

        source_id = str(doc_obj.get("source_id", ""))
        url = doc_obj.get("url", "")
        title = doc_obj.get("title", "")

        filter_query = {}
        if source_id:
            filter_query = {"source_id": source_id}
        elif url:
            filter_query = {"url": url}
        else:
            filter_query = {"title": title}

        res = collection.update_one(
            filter_query,
            {"$set": doc_obj},
            upsert=True
        )

        if res.upserted_id:
            upserted_count += 1
        elif res.modified_count > 0:
            updated_count += 1

    total_in_db = collection.count_documents({})
    logfire.info("MongoDB Ingestion Complete. Upserted new: {new}, Updated: {upd}, Total docs in collection '{col}': {total}",
                 new=upserted_count, upd=updated_count, col=collection_name, total=total_in_db)
    print(f"\n[MongoDB Ingestion Completed]")
    print(f" - Inserted new: {upserted_count}")
    print(f" - Updated existing: {updated_count}")
    print(f" - Total documents in collection '{collection_name}': {total_in_db}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vietlex Raw Legal Data MongoDB Indexer")
    parser.add_argument("data_dir", type=str, help="Path to raw data directory")
    parser.add_argument("--collection", type=str, default="raw_legal_documents", help="MongoDB collection name")
    parser.add_argument("--db", type=str, default="Legal-RAG", help="MongoDB database name")

    args = parser.parse_args()
    run_mongo_ingestion(args.data_dir, args.collection, args.db)
