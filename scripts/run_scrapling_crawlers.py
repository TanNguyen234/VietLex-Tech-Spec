import os
import sys
import json
import argparse
from typing import List, Dict, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler
from app.ingestion.crawlers.moj_crawler import MOJCrawler
from app.ingestion.scrapling_base import get_output_dir_for_source
from app.ingestion.schemas import LegalDocumentSchema

def get_crawler_and_source(url: str):
    if "vbpl.vn" in url:
        return VBPLCrawler(), "vbpl.vn"
    elif "quochoi.vn" in url:
        return VietlawCrawler(), "vietlaw.quochoi.vn"
    elif "moj.gov.vn" in url:
        return MOJCrawler(), "moj.gov.vn"
    else:
        raise ValueError(f"Unsupported URL domain: {url}")

def run_crawler_job(urls: List[str], is_test_run: bool = False, mock: bool = False, custom_out_dir: Optional[str] = None) -> Dict[str, int]:
    summary = {"vbpl.vn": 0, "vietlaw.quochoi.vn": 0, "moj.gov.vn": 0}
    
    for url in urls:
        crawler, source = get_crawler_and_source(url)
        out_dir = custom_out_dir if custom_out_dir else get_output_dir_for_source(source)
        
        if mock:
            doc = LegalDocumentSchema(
                source_id="130000" if "vbpl" in source else ("999" if "vietlaw" in source else "888"),
                source=source,
                url=url,
                title=f"Sample Test Document for {source}",
                official_number="31/2024/QH15" if "vbpl" in source else "80/2015/QH13",
                issued_date="2024-01-18",
                effective_date="2025-01-01",
                full_text=f"Nội dung quy định thử nghiệm bóc tách từ cổng thông tin {source}. Đã hoàn tất xử lý HTML và kiểm tra Schema.",
                attributes={"Cơ quan ban hành": "Quốc hội / Bộ Tư pháp", "Tình trạng": "Còn hiệu lực"},
                relations={"Văn bản dẫn chiếu": ["https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=100"]}
            )
        else:
            doc = crawler.parse_document(url)

        if doc:
            filename = f"{doc.source_id}.json"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(doc.model_dump(), f, ensure_ascii=False, indent=2)
            summary[source] += 1

    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Scrapling legal crawlers")
    parser.add_argument("--urls", nargs="+", required=True, help="List of URLs to crawl")
    parser.add_argument("--test", action="store_true", help="Perform sample test crawl only")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing setup")
    args = parser.parse_args()
    
    summary = run_crawler_job(args.urls, is_test_run=args.test, mock=args.mock)
    print("Crawl summary:", json.dumps(summary, indent=2))
