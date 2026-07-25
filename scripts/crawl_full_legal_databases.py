import os
import sys
import time
import json
import re
import logging
import argparse
import threading
from typing import List, Dict, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler
from app.ingestion.crawlers.moj_crawler import MOJCrawler
from app.ingestion.scrapling_base import get_output_dir_for_source

# Create logs directory
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "full_crawl_progress.log")

# File logger handler
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logger = logging.getLogger("FullCrawl")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

# Stream handler for console stdout logs
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stream_handler)

SITE_CONFIGS = {
    "vbpl": {
        "source": "vbpl.vn",
        "url_template": "https://vbpl.vn/TW/Pages/vbpq-toan-van.aspx?dvid=13&ItemID={item_id}&Keyword=&view_adult=true",
        "crawler_cls": VBPLCrawler
    },
    "vietlaw": {
        "source": "vietlaw.quochoi.vn",
        "url_template": "https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID={item_id}",
        "crawler_cls": VietlawCrawler
    },
    "moj": {
        "source": "moj.gov.vn",
        "url_template": "https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID={item_id}",
        "crawler_cls": MOJCrawler
    }
}

# Thread-local storage for crawlers
_thread_local = threading.local()

def get_thread_crawler(site_key: str):
    if not hasattr(_thread_local, "crawlers"):
        _thread_local.crawlers = {}
    if site_key not in _thread_local.crawlers:
        crawler_cls = SITE_CONFIGS[site_key]["crawler_cls"]
        _thread_local.crawlers[site_key] = crawler_cls()
    return _thread_local.crawlers[site_key]

def process_single_url(site_key: str, url: str, out_dir: str) -> str:
    item_id_match = re.search(r"ItemID=(\d+)", url, re.IGNORECASE) or re.search(r"--([a-zA-Z0-9_-]+)$", url)
    doc_id = item_id_match.group(1) if item_id_match else str(abs(hash(url)))
    filepath = os.path.join(out_dir, f"{doc_id}.json")

    crawler = get_thread_crawler(site_key)
    try:
        doc = crawler.parse_document(url)
        if doc and (doc.full_text or doc.title) and len(str(doc.full_text).strip()) > 10:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json.dumps(doc.model_dump(), ensure_ascii=False, indent=2))
            return "SUCCESS"
        return "EMPTY_OR_NOT_FOUND"
    except Exception as e:
        logger.debug(f"Error crawling {url}: {e}")
        return "FAILED"

def load_manifest_urls(manifest_path: str, site_key: str) -> List[str]:
    if not os.path.exists(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(site_key, [])
    except Exception as e:
        logger.warning(f"Failed to read manifest file {manifest_path}: {e}")
        return []

def run_site_bulk_crawl(
    site_key: str, 
    start_id: int = None, 
    end_id: int = None, 
    urls: List[str] = None, 
    max_workers: int = 15, 
    resume: bool = True
) -> Dict[str, int]:
    config = SITE_CONFIGS[site_key]
    source = config["source"]
    out_dir = get_output_dir_for_source(source)
    os.makedirs(out_dir, exist_ok=True)

    manifest_path = os.path.join(PROJECT_ROOT, "data", "discovered_urls_manifest.json")
    if urls is None:
        urls = load_manifest_urls(manifest_path, site_key)

    # Fallback to ID range if no URLs in manifest
    if not urls and start_id is not None and end_id is not None:
        urls = [config["url_template"].format(item_id=i) for i in range(start_id, end_id + 1)]

    total_target = len(urls)
    if total_target == 0:
        logger.warning(f"[{site_key.upper()}] No URLs available to crawl! Run harvest_legal_catalog_urls.py first.")
        return {"SUCCESS": 0, "SKIPPED": 0, "EMPTY_OR_NOT_FOUND": 0, "FAILED": 0}

    # 1. Fast RAM Pre-filtering of existing files (<0.01 sec)
    existing_files: Set[str] = set()
    if resume and os.path.exists(out_dir):
        for f in os.listdir(out_dir):
            if f.endswith(".json"):
                existing_files.add(f[:-5])

    pending_urls = []
    for u in urls:
        m = re.search(r"ItemID=(\d+)", u, re.IGNORECASE) or re.search(r"--([a-zA-Z0-9_-]+)$", u)
        doc_id = m.group(1) if m else str(abs(hash(u)))
        if not resume or doc_id not in existing_files:
            pending_urls.append(u)

    skipped_count = total_target - len(pending_urls)

    logger.info("=" * 70)
    logger.info(f"STARTING SCRAPLING CRAWL FOR {site_key.upper()} ({source})")
    logger.info(f"Target URLs Count : {total_target:,}")
    logger.info(f"Already Downloaded: {skipped_count:,} items (Skipped instantly in RAM)")
    logger.info(f"Pending to Crawl  : {len(pending_urls):,} items")
    logger.info(f"Output Directory  : {out_dir} | Threads: {max_workers}")
    logger.info("=" * 70)

    stats = {"SUCCESS": 0, "SKIPPED": skipped_count, "EMPTY_OR_NOT_FOUND": 0, "FAILED": 0}
    if not pending_urls:
        logger.info(f"[{site_key.upper()}] All {total_target:,} documents are already downloaded! Nothing to do.")
        return stats

    start_time = time.time()
    total_pending = len(pending_urls)
    processed = 0

    # tqdm progress bar integration
    with tqdm(
        total=total_pending,
        desc=f"[{site_key.upper()}] Crawling",
        unit="doc",
        dynamic_ncols=True,
        leave=True
    ) as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_single_url, site_key, url, out_dir): url
                for url in pending_urls
            }

            for future in as_completed(futures):
                processed += 1
                res = future.result()
                stats[res] = stats.get(res, 0) + 1

                # Update tqdm bar & statistics
                pbar.update(1)
                pbar.set_postfix(
                    ok=stats["SUCCESS"],
                    empty=stats["EMPTY_OR_NOT_FOUND"],
                    err=stats["FAILED"]
                )

                # Periodic file log update every 200 docs
                if processed % 200 == 0 or processed == total_pending:
                    elapsed = time.time() - start_time
                    speed = processed / elapsed if elapsed > 0 else 0
                    remaining = total_pending - processed
                    eta_minutes = (remaining / speed) / 60 if speed > 0 else 0
                    
                    file_handler.emit(logging.LogRecord(
                        name="FullCrawl", level=logging.INFO, pathname="", lineno=0,
                        msg=(
                            f"[{site_key.upper()}] Progress: {processed:,}/{total_pending:,} ({processed/total_pending*100:.1f}%) | "
                            f"Success: {stats['SUCCESS']:,} | 404/Empty: {stats['EMPTY_OR_NOT_FOUND']:,} | "
                            f"Failed: {stats['FAILED']:,} | Speed: {speed:.1f} docs/sec | ETA: {eta_minutes:.1f} min"
                        ),
                        args=(), exc_info=None
                    ))

    total_time = time.time() - start_time
    logger.info(
        f"FINISHED {site_key.upper()} IN {total_time/60:.2f} MINUTES. "
        f"Final Summary -> Success: {stats['SUCCESS']:,}, Skipped: {stats['SKIPPED']:,}, "
        f"Not Found: {stats['EMPTY_OR_NOT_FOUND']:,}, Failed: {stats['FAILED']:,}"
    )
    return stats

def main():
    parser = argparse.ArgumentParser(description="Production Legal Database Scrapling Crawler with tqdm ETA Engine")
    parser.add_argument("--site", choices=["all", "vbpl", "vietlaw", "moj"], default="all", help="Site to crawl (default: all)")
    parser.add_argument("--start-id", type=int, help="Start ItemID range")
    parser.add_argument("--end-id", type=int, help="End ItemID range")
    parser.add_argument("--workers", type=int, default=15, help="Number of worker threads (default: 15)")
    parser.add_argument("--no-resume", action="store_true", help="Re-crawl existing files")

    args = parser.parse_args()
    resume = not args.no_resume
    sites_to_run = ["vbpl", "vietlaw", "moj"] if args.site == "all" else [args.site]

    manifest_path = os.path.join(PROJECT_ROOT, "data", "discovered_urls_manifest.json")
    
    # Global ETA Calculation for multi-site crawl
    total_urls_all_sites = 0
    site_url_counts = {}
    for s in sites_to_run:
        u_list = load_manifest_urls(manifest_path, s)
        site_url_counts[s] = len(u_list)
        total_urls_all_sites += len(u_list)

    global_start_time = time.time()

    logger.info("=" * 80)
    logger.info("GLOBAL LEGAL CRAWLER EXECUTION ENGINE INITIALIZED")
    logger.info(f"Target Sites       : {', '.join([s.upper() for s in sites_to_run])}")
    logger.info(f"Total Combined URLs: {total_urls_all_sites:,}")
    for s in sites_to_run:
        logger.info(f"  - {s.upper():<10}: {site_url_counts[s]:,} URLs")
    logger.info(f"Worker Threads     : {args.workers}")
    logger.info(f"Resume Existing    : {resume}")
    logger.info("=" * 80)

    overall_stats = {"SUCCESS": 0, "SKIPPED": 0, "EMPTY_OR_NOT_FOUND": 0, "FAILED": 0}

    for idx, site in enumerate(sites_to_run, 1):
        logger.info(f"\n>>> [Site {idx}/{len(sites_to_run)}] Executing crawl for {site.upper()}...")
        site_stats = run_site_bulk_crawl(
            site_key=site,
            start_id=args.start_id,
            end_id=args.end_id,
            max_workers=args.workers,
            resume=resume
        )
        for k in overall_stats:
            overall_stats[k] += site_stats.get(k, 0)

    total_global_time = time.time() - global_start_time
    logger.info("\n" + "=" * 80)
    logger.info("ALL CRAWLING JOBS COMPLETED!")
    logger.info(f"Total Execution Time : {total_global_time / 60:.2f} minutes")
    logger.info(f"Total Success        : {overall_stats['SUCCESS']:,} documents")
    logger.info(f"Total Skipped (RAM)  : {overall_stats['SKIPPED']:,} documents")
    logger.info(f"Total 404/Empty      : {overall_stats['EMPTY_OR_NOT_FOUND']:,} documents")
    logger.info(f"Total Failed         : {overall_stats['FAILED']:,} documents")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()
