import os
import sys
import glob
import gzip
import json
import re

# Ensure UTF-8 output encoding for Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.ingestion.parser import parse_legal_document

RAW_DATA_DIR = os.path.abspath("app/data/raw_data")
OUTPUT_DIR = os.path.abspath("app/data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def clean_val(val):
    if isinstance(val, list):
        return val[0] if val else ""
    return str(val) if val else ""

def transform_raw_to_chunks():
    gz_files = glob.glob(os.path.join(RAW_DATA_DIR, "crawled_doc_*.json.gz"))
    if not gz_files:
        print("[-] No crawled_doc_*.json.gz files found in app/data/raw_data/")
        return

    print(f"[+] Found {len(gz_files)} raw documents. Performing ETL Transformation to Article Chunks...")
    
    all_chunks = []
    sample_doc_chunks = []

    for fpath in gz_files:
        try:
            with gzip.open(fpath, "rt", encoding="utf-8") as f:
                doc_obj = json.load(f)
        except Exception as e:
            print(f"[-] Error loading {fpath}: {e}")
            continue

        source_id = str(doc_obj.get("source_id", ""))
        title = clean_val(doc_obj.get("title", ""))
        full_text = doc_obj.get("full_text", "").strip()
        attributes = doc_obj.get("attribute", {})

        if not full_text:
            continue

        official_number = clean_val(attributes.get("official_number"))
        document_type = clean_val(attributes.get("document_type"))
        effective_date = clean_val(attributes.get("effective_date"))
        issuing_body = clean_val(attributes.get("issuing_body/office/signer"))

        # Parse full_text into Article level chunks
        doc_chunks = parse_legal_document(full_text)
        
        # Fallback if regex parser yields no articles
        if not doc_chunks:
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            for idx, para in enumerate(paragraphs):
                doc_chunks.append({
                    "chapter": "",
                    "section": "",
                    "article": f"Đoạn {idx+1}",
                    "content": para
                })

        # Process each chunk into Vector DB Payload format
        for chunk in doc_chunks:
            article_raw = chunk.get("article", "").strip()
            content_text = chunk.get("content", "").strip()
            chapter_name = chunk.get("chapter", "").strip()
            section_name = chunk.get("section", "").strip()

            # Extract article title if present (e.g., "Điều 1. Phạm vi điều chỉnh" -> article: "Điều 1", article_title: "Phạm vi điều chỉnh")
            article_code = article_raw
            article_title = ""
            if "." in article_raw:
                parts = article_raw.split(".", 1)
                article_code = parts[0].strip()
                article_title = parts[1].strip()

            # Sanitize chunk ID
            safe_article_id = re.sub(r"[^\w\d_]", "_", article_code.lower())
            chunk_id = f"chunk_{source_id}_{safe_article_id}"

            chunk_payload = {
                "chunk_id": chunk_id,
                "text": content_text,
                "payload": {
                    "metadata": {
                        "source_id": source_id,
                        "official_number": official_number,
                        "title": title,
                        "document_type": document_type,
                        "issuing_body": issuing_body,
                        "effective_date": effective_date,
                        "chapter": chapter_name,
                        "section": section_name,
                        "article": article_code,
                        "article_title": article_title
                    },
                    "text": content_text
                }
            }

            all_chunks.append(chunk_payload)
            if source_id == "139264":
                sample_doc_chunks.append(chunk_payload)

    # Save complete chunked dataset
    out_all_path = os.path.join(OUTPUT_DIR, "chunked_kb_dataset.json")
    with open(out_all_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    # Save sample chunked file for doc 139264 (Bộ luật Lao động 2019)
    out_sample_path = os.path.join(OUTPUT_DIR, "sample_chunks_139264.json")
    with open(out_sample_path, "w", encoding="utf-8") as f:
        json.dump(sample_doc_chunks, f, ensure_ascii=False, indent=2)

    print(f"\n==================================================")
    print(f"ETL TRANSFORMATION COMPLETE:")
    print(f"  • Total Raw Documents Processed: {len(gz_files)}")
    print(f"  • Total Article Chunks Created:   {len(all_chunks):,}")
    print(f"  • Sample Chunks for Doc 139264:   {len(sample_doc_chunks)} chunks")
    print(f"  • Full Dataset File Saved to:     {out_all_path}")
    print(f"  • Sample Chunk File Saved to:     {out_sample_path}")
    print(f"==================================================")

if __name__ == "__main__":
    transform_raw_to_chunks()
