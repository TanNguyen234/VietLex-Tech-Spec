import os
import sys
import logging
from typing import List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.run_scrapling_crawlers import run_crawler_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def generate_sample_bulk_urls() -> List[str]:
    urls = []
    # VBPL URLs (Sample batch across item IDs)
    vbpl_ids = [130000, 130001, 130002, 130003, 130004, 130005, 130006, 130007, 130008, 130009]
    for sid in vbpl_ids:
        urls.append(f"https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID={sid}")

    # VietLaw URLs
    vietlaw_ids = [990, 991, 992, 993, 994, 995, 996, 997, 998, 999]
    for sid in vietlaw_ids:
        urls.append(f"https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID={sid}")

    # MOJ URLs
    moj_ids = [880, 881, 882, 883, 884, 885, 886, 887, 888, 889]
    for sid in moj_ids:
        urls.append(f"https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID={sid}")

    return urls

def main():
    logging.info("Starting Scrapling bulk crawl job across 3 legal portals...")
    urls = generate_sample_bulk_urls()
    summary = run_crawler_job(urls=urls, is_test_run=False, mock=False)
    logging.info(f"Bulk crawl completed. Summary: {summary}")

if __name__ == "__main__":
    main()
