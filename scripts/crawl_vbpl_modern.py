import os
import sys
import gzip
import json
import re
import html
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://vbpl.vn"

# Action IDs for Next.js Server Actions on vbpl.vn
SEARCH_ACTION_ID = "c529d164f28418e5898a834422629e64c6816af1"
DETAILS_ACTION_ID = "0fb12b3561faa05adec51a82efb3e4f4f427f07b"

HEADERS = {
    "Accept": "text-x-component",
    "Next-Router-State-Tree": '["",{"children":["__PAGE__",{},null,null]},null,null,true]',
    "Content-Type": "text/plain;charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

RAW_DATA_DIR = os.path.abspath("app/data/raw_data")
os.makedirs(RAW_DATA_DIR, exist_ok=True)

def clean_str(val):
    """Clean and decode string values."""
    if not val:
        return ""
    val = html.unescape(str(val)).strip()
    return val

def search_documents(keyword: str, page_number: int = 1, page_size: int = 20):
    """Searches documents via Next.js Server Action and returns items list and total."""
    headers = HEADERS.copy()
    headers["Next-Action"] = SEARCH_ACTION_ID
    
    payload = [{
        "keyword": keyword,
        "optionDoc": "title",
        "matchMode": "all_words",
        "pageNumber": page_number,
        "pageSize": page_size,
        "administrativeUnit": None,
        "agencyIds": None,
        "agencyLevel": None,
        "docNum": None,
        "docType": None,
        "documentName": None,
        "documentType": None,
        "effFromBegin": None,
        "effFromEnd": None,
        "effStatus": None,
        "effToEnd": None,
        "effToFrom": None,
        "fieldTypeIds": None,
        "groupVbpl": None,
        "issueDateFrom": None,
        "issueDateTo": None,
        "status": None
    }]
    
    try:
        res = requests.post(BASE_URL, headers=headers, json=payload, timeout=30.0)
        res.raise_for_status()
        res_text = res.content.decode("utf-8", errors="replace")
        
        # Parse RSC payload line starting with 1:
        for line in res_text.split("\n"):
            if line.startswith("1:"):
                data_str = line[2:].strip()
                data = json.loads(data_str)
                return data.get("items", []), data.get("total", 0)
        return [], 0
    except Exception as e:
        print(f"[-] Search error for keyword '{keyword}', page {page_number}: {e}")
        return [], 0

def fetch_document_details(doc_id: str):
    """Fetches document metadata and HTML body using Next.js Server Action."""
    headers = HEADERS.copy()
    headers["Next-Action"] = DETAILS_ACTION_ID
    
    payload = [str(doc_id)]
    
    try:
        res = requests.post(BASE_URL, headers=headers, json=payload, timeout=45.0)
        res.raise_for_status()
        text = res.content.decode("utf-8", errors="replace")
        
        # Find metadata JSON at the end (starting with 1:{" or 1:[)
        idx = text.rfind('1:{"')
        if idx == -1:
            idx = text.rfind('1:[')
            
        if idx == -1:
            print(f"[-] Metadata block not found for doc {doc_id}")
            return None
            
        metadata_json_str = text[idx + 2:].strip()
        metadata = json.loads(metadata_json_str)
        if isinstance(metadata, list) and len(metadata) > 0:
            metadata = metadata[0]
            
        # Extract HTML Content block
        start_idx = 0
        match_html = re.search(r'(?:^|\n)(2:T[0-9a-fA-F]+,)', text)
        if match_html:
            start_idx = text.find(match_html.group(1)) + len(match_html.group(1))
        else:
            match_fallback = re.search(r'(?:^|\n)(2:)', text)
            if match_fallback:
                start_idx = text.find(match_fallback.group(1)) + len(match_fallback.group(1))
                
        raw_html = text[start_idx:idx].strip()
        if raw_html.startswith('"') and raw_html.endswith('"'):
            try:
                raw_html = json.loads(raw_html)
            except Exception:
                pass
                
        # Unescape HTML entities
        raw_html = html.unescape(raw_html)

        # Extract clean text using BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")
        
        # Remove unneeded elements
        for element in soup(["script", "style", "meta", "link"]):
            element.decompose()
            
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
        full_text = "\n".join([line for line in lines if line])

        doc_type_name = ""
        doc_type = metadata.get("docType")
        if isinstance(doc_type, dict):
            doc_type_name = doc_type.get("name", "")
        elif isinstance(doc_type, str):
            doc_type_name = doc_type

        # Structure document object for RAG
        doc_object = {
            "source_id": str(doc_id),
            "source": "vbpl.vn",
            "url": f"https://vbpl.vn/van-ban/chi-tiet/{doc_id}",
            "title": clean_str(metadata.get("title") or metadata.get("name") or f"Văn bản {doc_id}"),
            "last_updated_time": clean_str(metadata.get("updatedAt")),
            "html_text": raw_html,
            "full_text": full_text,
            "attribute": {
                "official_number": [clean_str(metadata.get("docNum"))] if metadata.get("docNum") else [],
                "document_info": [clean_str(metadata.get("summary"))] if metadata.get("summary") else [],
                "issuing_body/office/signer": [clean_str(metadata.get("agencyName"))] if metadata.get("agencyName") else [],
                "document_type": [clean_str(doc_type_name)] if doc_type_name else [],
                "effective_area": clean_str(metadata.get("administrativeUnit")) or "Toàn quốc",
                "collection_source": ["vbpl.vn"],
                "issued_date": clean_str(metadata.get("issueDate")),
                "effective_date": clean_str(metadata.get("effFrom")),
                "enforced_date": clean_str(metadata.get("effFrom")),
                "expiry_date": clean_str(metadata.get("effTo")) if metadata.get("effTo") else None
            },
            "schema": {}
        }
        return doc_object
    except Exception as e:
        print(f"[-] Error fetching details for doc {doc_id}: {e}")
        return None

def save_doc_gz(doc_object: dict):
    """Saves a document object to app/data/raw_data/ as gzip json."""
    doc_id = doc_object["source_id"]
    output_path = os.path.join(RAW_DATA_DIR, f"crawled_doc_{doc_id}.json.gz")
    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        json.dump(doc_object, f, ensure_ascii=False, indent=2)
    return output_path

def crawl_batch_for_keywords(keywords, max_pages=3, max_workers=5):
    """Executes a batch crawl for given keywords across multiple pages."""
    print("==================================================")
    print("STARTING BATCH CRAWL VIA NEXT.JS SERVER ACTIONS")
    print(f"Keywords: {keywords}")
    print(f"Max Pages per Keyword: {max_pages}")
    print("==================================================")
    
    doc_items = {}
    for kw in keywords:
        print(f"\n[+] Searching for keyword: '{kw}'...")
        items_kw, total = search_documents(kw, page_number=1, page_size=20)
        print(f"    Total results found for '{kw}': {total}")
        for item in items_kw:
            doc_items[str(item["id"])] = item
            
        # Fetch additional pages
        for page in range(2, max_pages + 1):
            items_p, _ = search_documents(kw, page_number=page, page_size=20)
            if not items_p:
                break
            for item in items_p:
                doc_items[str(item["id"])] = item

    unique_doc_ids = list(doc_items.keys())
    print(f"\n[+] Total unique document IDs collected to crawl: {len(unique_doc_ids)}")
    
    saved_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_document_details, doc_id): doc_id for doc_id in unique_doc_ids}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Crawling Documents"):
            doc_obj = future.result()
            if doc_obj and doc_obj.get("full_text"):
                save_doc_gz(doc_obj)
                saved_count += 1
                
    print(f"\n==================================================")
    print(f"CRAWL COMPLETE: Successfully saved {saved_count}/{len(unique_doc_ids)} documents.")
    print(f"Saved location: {RAW_DATA_DIR}")
    print("==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Modern vbpl.vn Batch Scraper")
    parser.add_argument("--keywords", nargs="+", default=["Hiến pháp", "Bộ luật", "Luật"], help="Keywords to search and crawl")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages to crawl per keyword")
    parser.add_argument("--workers", type=int, default=4, help="Thread pool size")
    args = parser.parse_args()

    crawl_batch_for_keywords(args.keywords, max_pages=args.pages, max_workers=args.workers)
