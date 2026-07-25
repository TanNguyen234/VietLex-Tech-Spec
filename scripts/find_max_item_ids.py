import os
import sys
import time
import json
import logging
from typing import Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler
from app.ingestion.crawlers.moj_crawler import MOJCrawler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CRAWLER_CLASSES = {
    "vbpl": (VBPLCrawler, "https://vbpl.vn/TW/Pages/vbpq-toan-van.aspx?dvid=13&ItemID={item_id}&Keyword=&view_adult=true"),
    "vietlaw": (VietlawCrawler, "https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID={item_id}"),
    "moj": (MOJCrawler, "https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID={item_id}")
}

def check_single_id_valid(site_key: str, item_id: int, crawler) -> bool:
    url_tmpl = CRAWLER_CLASSES[site_key][1]
    url = url_tmpl.format(item_id=item_id)
    try:
        doc = crawler.parse_document(url)
        if doc and doc.full_text and len(doc.full_text.strip()) > 50:
            return True
    except Exception:
        pass
    return False

def check_window_has_valid(site_key: str, center_id: int, window_size: int = 100, workers: int = 10) -> bool:
    """Parallel check a sample window around center_id to see if real documents exist"""
    crawler_cls = CRAWLER_CLASSES[site_key][0]
    sample_ids = list(range(center_id, center_id + window_size, max(1, window_size // 10)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(check_single_id_valid, site_key, sid, crawler_cls()): sid for sid in sample_ids}
        for future in as_completed(futures):
            if future.result():
                return True
    return False

def binary_search_min_id(site_key: str, low: int, high: int) -> int:
    logging.info(f"[{site_key.upper()}] Binary Search for MIN ItemID between {low:,} and {high:,}...")
    start_time = time.time()
    best_min = high
    step = 0

    while low <= high:
        step += 1
        mid = (low + high) // 2
        logging.info(f"[{site_key.upper()}] [MIN] Step {step}: Testing mid={mid:,} (Range: [{low:,} .. {high:,}])")

        if check_window_has_valid(site_key, mid, window_size=200):
            best_min = mid
            high = mid - 1  # Try searching lower
        else:
            low = mid + 1   # Try searching higher

    elapsed = time.time() - start_time
    logging.info(f"[{site_key.upper()}] Discovered MIN ItemID: {best_min:,} in {elapsed:.2f}s")
    return best_min

def binary_search_max_id(site_key: str, low: int, high: int) -> int:
    logging.info(f"[{site_key.upper()}] Binary Search for MAX ItemID between {low:,} and {high:,}...")
    start_time = time.time()
    best_max = low
    step = 0

    while low <= high:
        step += 1
        mid = (low + high) // 2
        logging.info(f"[{site_key.upper()}] [MAX] Step {step}: Testing mid={mid:,} (Range: [{low:,} .. {high:,}])")

        if check_window_has_valid(site_key, mid, window_size=200):
            best_max = mid + 200
            low = mid + 1   # Try searching higher
        else:
            high = mid - 1  # Try searching lower

    elapsed = time.time() - start_time
    logging.info(f"[{site_key.upper()}] Discovered MAX ItemID: {best_max:,} in {elapsed:.2f}s")
    return best_max

def discover_site_bounds(site_key: str, search_range: Tuple[int, int]) -> Tuple[int, int]:
    low, high = search_range
    min_id = binary_search_min_id(site_key, low, high)
    max_id = binary_search_max_id(site_key, min_id, high)
    return min_id, max_id

def main():
    logging.info("=" * 70)
    logging.info("DYNAMIC MULTI-THREADED BINARY SEARCH FOR REAL MIN & MAX ITEM IDS")
    logging.info("=" * 70)

    bounds = {
        "vbpl": (1000, 170000),
        "vietlaw": (1, 50000),
        "moj": (1, 30000)
    }

    results = {}
    for site, r in bounds.items():
        min_id, max_id = discover_site_bounds(site, r)
        results[site] = (min_id, max_id)

    print("\n" + "=" * 70)
    print("VERIFIED REAL ITEM ID BOUNDS:")
    for site, (min_id, max_id) in results.items():
        print(f"  - {site.upper()}: start_id = {min_id:,}, end_id = {max_id:,}")
    print("=" * 70)

    # Save discovered bounds to data/discovered_bounds.json
    summary_file = os.path.join(PROJECT_ROOT, "data", "discovered_bounds.json")
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logging.info(f"Saved verified bounds to {summary_file}")

if __name__ == "__main__":
    main()
