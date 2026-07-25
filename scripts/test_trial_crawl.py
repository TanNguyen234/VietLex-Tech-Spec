import os
import sys
import time
import json
import logging
from typing import Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler
from app.ingestion.crawlers.moj_crawler import MOJCrawler
from app.ingestion.schemas import LegalDocumentSchema

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrialCrawl")

SAMPLE_DIR = os.path.join(PROJECT_ROOT, "data", "scrapling_raw", "trial_samples")
os.makedirs(SAMPLE_DIR, exist_ok=True)

CRAWLER_CLASSES = {
    "vbpl": VBPLCrawler,
    "vietlaw": VietlawCrawler,
    "moj": MOJCrawler
}

def load_one_url_per_site() -> Dict[str, str]:
    manifest_path = os.path.join(PROJECT_ROOT, "data", "discovered_urls_manifest.json")
    if not os.path.exists(manifest_path):
        logger.error(f"Manifest file not found at {manifest_path}! Run harvest_legal_catalog_urls.py first.")
        sys.exit(1)
        
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    target_urls = {}
    for site in ["vbpl", "vietlaw", "moj"]:
        urls = data.get(site, [])
        if urls:
            target_urls[site] = urls[0]
        else:
            # Fallback test URLs if manifest lacks a site
            fallbacks = {
                "vbpl": "https://vbpl.vn/van-ban/chi-tiet/thong-tu-17-2026-tt-nhnn-sua-doi-bo-sung-mot-so-dieu-cua-cac-thong-tu-trong-linh-vuc-quan-ly-ngoai-hoi-lien-quan-den-phan-cap-don-gian-hoa-thu-tuc-hanh-chinh--784d6e20-5d60-11f1-a1f9-55b80579da65",
                "vietlaw": "https://vietlaw.quochoi.vn/Pages/vbpq-toan-van.aspx?ItemID=1",
                "moj": "https://moj.gov.vn/portal/van-ban/vb-chi-dao-dieu-hanh.html"
            }
            target_urls[site] = fallbacks[site]
            
    return target_urls

def run_trial():
    logger.info("=" * 80)
    logger.info("STARTING 3-SITE LIVE TRIAL CRAWL (1 LINK PER SITE)")
    logger.info("=" * 80)
    
    target_urls = load_one_url_per_site()
    results = []
    
    for site, url in target_urls.items():
        logger.info(f"\n[Testing Site: {site.upper()}]")
        logger.info(f"Target URL: {url}")
        
        start_time = time.time()
        crawler = CRAWLER_CLASSES[site]()
        
        try:
            doc: LegalDocumentSchema = crawler.parse_document(url)
            elapsed = time.time() - start_time
            
            if doc and (doc.full_text or doc.title):
                filename = f"{site}_sample.json"
                out_path = os.path.join(SAMPLE_DIR, filename)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(doc.model_dump(), f, ensure_ascii=False, indent=2)
                    
                text_len = len(doc.full_text.strip()) if doc.full_text else 0
                results.append({
                    "Site": site.upper(),
                    "Status": "SUCCESS ✅",
                    "Latency": f"{elapsed:.2f}s",
                    "Title": doc.title[:60] + "..." if len(doc.title) > 60 else doc.title,
                    "Official No": doc.official_number or "N/A",
                    "Text Length": f"{text_len:,} chars",
                    "File Saved": out_path
                })
                logger.info(f"-> SUCCESS in {elapsed:.2f}s | Title: {doc.title}")
            else:
                results.append({
                    "Site": site.upper(),
                    "Status": "EMPTY ⚠️",
                    "Latency": f"{elapsed:.2f}s",
                    "Title": "N/A",
                    "Official No": "N/A",
                    "Text Length": "0 chars",
                    "File Saved": "None"
                })
                logger.warning(f"-> EMPTY / NOT FOUND in {elapsed:.2f}s")
                
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"-> ERROR in {elapsed:.2f}s: {e}")
            results.append({
                "Site": site.upper(),
                "Status": "FAILED ❌",
                "Latency": f"{elapsed:.2f}s",
                "Title": "N/A",
                "Official No": "N/A",
                "Text Length": "0 chars",
                "File Saved": "None"
            })
            
    logger.info("\n" + "=" * 80)
    logger.info("3-SITE TRIAL CRAWL EVALUATION SUMMARY")
    logger.info("=" * 80)
    
    for r in results:
        logger.info(f"• [{r['Site']}] Status: {r['Status']} | Time: {r['Latency']} | Text: {r['Text Length']}")
        logger.info(f"  Title: {r['Title']}")
        logger.info(f"  Official No: {r['Official No']}")
        logger.info(f"  Saved to: {r['File Saved']}")
        logger.info("-" * 80)

if __name__ == "__main__":
    run_trial()
