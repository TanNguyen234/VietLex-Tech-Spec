import os
import re
import json
import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

def parse_sitemap_index_xml(xml_content: str) -> List[str]:
    return re.findall(r'<loc>(.*?)</loc>', xml_content)

def harvest_vbpl_sitemap_urls(max_sitemaps: int = 35) -> List[str]:
    logger.info("Harvesting VBPL document URLs from sitemap.xml...")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    
    root_res = session.get("https://vbpl.vn/sitemap.xml", timeout=15)
    sitemaps = parse_sitemap_index_xml(root_res.text)[:max_sitemaps]
    
    document_urls = []
    for idx, sm_url in enumerate(sitemaps, 1):
        try:
            r = session.get(sm_url, timeout=20)
            urls = parse_sitemap_index_xml(r.text)
            doc_urls = [u for u in urls if "/van-ban/chi-tiet/" in u or "ItemID=" in u]
            document_urls.extend(doc_urls)
            logger.info(f"[VBPL Sitemap] {idx}/{len(sitemaps)} ({sm_url}) -> {len(doc_urls)} URLs (Total: {len(document_urls)})")
        except Exception as e:
            logger.warning(f"Error fetching sitemap {sm_url}: {e}")
            
    return list(set(document_urls))

def harvest_vietlaw_catalog_urls(max_categories: int = 23) -> List[str]:
    logger.info("Harvesting VietLaw document URLs from category listings...")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    
    # Challenge cookie D1N handling
    r = session.get("https://vietlaw.quochoi.vn/", timeout=15)
    m = re.search(r'D1N=([a-f0-9]+)', r.text)
    if m:
        session.cookies.set("D1N", m.group(1), domain="vietlaw.quochoi.vn")
        
    doc_urls = []
    for cat_id in range(1, max_categories + 1):
        cat_url = f"https://vietlaw.quochoi.vn/Pages/danh-sach-van-ban.aspx?idLoaiVanBan={cat_id}"
        try:
            res = session.get(cat_url, timeout=15)
            links = re.findall(r'href=[\"\'](/Pages/vbpq-toan-van\.aspx\?ItemID=\d+)[\"\']', res.text)
            full_links = [f"https://vietlaw.quochoi.vn{l}" for l in links]
            doc_urls.extend(full_links)
            logger.info(f"[VietLaw Catalog] Cat {cat_id}/{max_categories} -> {len(full_links)} URLs")
        except Exception as e:
            logger.warning(f"Error fetching VietLaw cat {cat_id}: {e}")
            
    return list(set(doc_urls))

def harvest_moj_catalog_urls(max_pages: int = 10) -> List[str]:
    logger.info("Harvesting MOJ document URLs from portal listings...")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    
    sections = [
        "https://moj.gov.vn/portal/van-ban/vb-chi-dao-dieu-hanh.html",
        "https://moj.gov.vn/portal/tin-tuc/chuyen-muc/van-ban-chinh-sach-moi.html"
    ]
    
    doc_urls = []
    for sec in sections:
        try:
            res = session.get(sec, timeout=15, verify=False)
            if res.status_code == 200:
                links = re.findall(r'href=[\"\'](/portal/[^\"]+/(?:chi-tiet|van-ban)/[^\"]+)[\"\']', res.text)
                full_links = [f"https://moj.gov.vn{l}" for l in links]
                doc_urls.extend(full_links)
                logger.info(f"[MOJ Catalog] Section {sec} -> Discovered {len(full_links)} links")
        except Exception as e:
            logger.warning(f"Error fetching MOJ section {sec}: {e}")
            
    if not doc_urls:
        doc_urls = ["https://moj.gov.vn/portal/van-ban/vb-chi-dao-dieu-hanh.html"]
        
    return list(set(doc_urls))

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    manifest: Dict[str, List[str]] = {
        "vbpl": harvest_vbpl_sitemap_urls(max_sitemaps=35),
        "vietlaw": harvest_vietlaw_catalog_urls(max_categories=23),
        "moj": harvest_moj_catalog_urls()
    }
    
    out_file = os.path.join("data", "discovered_urls_manifest.json")
    os.makedirs("data", exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        
    logger.info(f"SUCCESS: Saved manifest to {out_file}:")
    logger.info(f"  - VBPL: {len(manifest['vbpl']):,} URLs")
    logger.info(f"  - VietLaw: {len(manifest['vietlaw']):,} URLs")
    logger.info(f"  - MOJ: {len(manifest['moj']):,} URLs")

if __name__ == "__main__":
    main()

