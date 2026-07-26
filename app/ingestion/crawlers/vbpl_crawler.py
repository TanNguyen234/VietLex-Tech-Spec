import re
import json
import logging
from typing import Optional, List
from bs4 import BeautifulSoup
from scrapling import Selector
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

logger = logging.getLogger(__name__)

ALLOWED_VBPL_PREFIXES = (
    "nghi-dinh", "quyet-dinh", "sac-lenh", "nghi-quyet", 
    "thong-tu", "chi-thi", "luat", "bo-luat"
)

def is_valid_vbpl_legal_url(url: str) -> bool:
    slug = url.split("/")[-1].lower()
    return any(slug.startswith(prefix) or f"-{prefix}-" in slug or f"/{prefix}-" in url.lower() for prefix in ALLOWED_VBPL_PREFIXES)

class VBPLCrawler(BaseLegalCrawler):
    def discover_catalog_urls(self, max_pages: int = 10) -> List[str]:
        """Harvests real live legal document URLs from VBPL search catalog listings using Scrapling"""
        urls = []
        base_search = "http://vbpl.vn/VBQPPL_UserControls/Publishing/TimKiem/pKetQuaTimKiem.aspx?dvid=13&IsVietNamese=True&type=0&stemp=1&TimTrong1=VBPQFulltext&TimTrong1=Title&order=VBPQNgayBanHanh&TypeOfOrder=False&RowPerPage=50&Page="
        
        for page in range(1, max_pages + 1):
            target_url = base_search + str(page)
            try:
                res = self.fetch_page(target_url)
                html_text = res.body.decode("utf-8", errors="ignore") if hasattr(res, "body") else (res.text if hasattr(res, "text") else str(res))
                if html_text:
                    sel = Selector(html_text)
                    hrefs = sel.css("a::attr(href)").getall()
                    found = []
                    for h in hrefs:
                        h_str = str(h).strip()
                        if "ItemID=" in h_str or "/van-ban/chi-tiet/" in h_str:
                            if h_str.startswith("/"):
                                full_url = f"https://vbpl.vn{h_str}"
                            elif not h_str.startswith("http"):
                                full_url = f"https://vbpl.vn/{h_str}"
                            else:
                                full_url = h_str
                            if is_valid_vbpl_legal_url(full_url) and full_url not in urls:
                                urls.append(full_url)
                                found.append(full_url)
                    logger.info(f"[VBPL Catalog] Page {page}/{max_pages} -> Discovered {len(found)} valid live links")
                    if not found and page > 1:
                        break
            except Exception as e:
                logger.warning(f"[VBPL Catalog] Error on page {page}: {e}")
                break
        return urls

    def parse_document_from_html(self, url: str, html_content: str, attr_html: str = "", schema_html: str = "") -> Optional[LegalDocumentSchema]:
        if not html_content or len(html_content.strip()) < 100:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        
        # Title check for 404
        t_tag = soup.find("title")
        page_title = t_tag.get_text().strip() if t_tag else ""
        if page_title.startswith("Trang không tồn tại") or page_title.startswith("404"):
            return None

        # Schema.org metadata extraction
        schema_meta = {}
        for s in soup.find_all("script", type="application/ld+json"):
            stext = s.get_text().strip()
            if stext and "Legislation" in stext:
                try:
                    data = json.loads(stext)
                    if isinstance(data, dict) and data.get("@type") == "Legislation":
                        schema_meta = data
                        break
                except Exception:
                    pass

        # Title extraction
        title = schema_meta.get("name", "")
        if not title:
            title = page_title.split("|")[0].strip() if page_title else ""
        if not title or title == "Đang tải dữ liệu...":
            bm_titles = soup.select(".box-map a")
            title = bm_titles[-1].get_text(strip=True) if bm_titles else "Văn bản pháp luật"

        # Metadata extraction
        doc_type = schema_meta.get("legislationType", "")
        official_num = schema_meta.get("legislationIdentifier", "")
        issued_date = schema_meta.get("legislationDate", "")
        if issued_date and "T" in str(issued_date):
            issued_date = str(issued_date).split("T")[0]

        passed_by = schema_meta.get("legislationPassedBy", {})
        issuing_org = passed_by.get("name", "") if isinstance(passed_by, dict) else (passed_by if isinstance(passed_by, str) else "")

        status_val = ""
        if "legislationLegalForce" in schema_meta:
            force = schema_meta.get("legislationLegalForce")
            if force == "NotInForce":
                status_val = "Hết hiệu lực"
            elif force == "InForce":
                status_val = "Còn hiệu lực"

        atts = {}
        if attr_html and "404 -" not in attr_html:
            attr_soup = BeautifulSoup(attr_html, "html.parser")
            for row in attr_soup.find_all("tr"):
                lbl = row.find(class_="label")
                val = row.find("td", class_=lambda c: c != "label") if lbl else None
                if lbl and val:
                    atts[lbl.get_text(strip=True)] = val.get_text(strip=True)

        if not doc_type:
            doc_type = atts.get("Loại văn bản", "")
        if not official_num:
            official_num = atts.get("Số ký hiệu", "")
        if not issued_date:
            issued_date = atts.get("Ngày ban hành", "")
        if not issuing_org:
            issuing_org = atts.get("Cơ quan ban hành", "")
        if not status_val:
            status_val = atts.get("Tình trạng hiệu lực", "")

        # Clean HTML for body extraction
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer"]):
            tag.extract()

        sel = Selector(str(soup))
        fulltext_el = sel.css(".fulltext")
        if fulltext_el:
            raw_text = "\n".join(fulltext_el.css("::text").getall())
        else:
            raw_text = "\n".join(sel.css("::text").getall())

        lines = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line or line.startswith("self.__next") or line.startswith("function()") or "document.cookie" in line or "ALLOWED_ORIGINS" in line or "frame-busting" in line or "cleanupExtensionAttributes" in line:
                continue
            lines.append(line)
        full_text = "\n".join(lines)

        # Fallback if full_text is short or CSR placeholder, construct rich summary from Schema.org metadata
        if len(full_text) < 50 or "Đang tải dữ liệu" in full_text or "Portal VBPL" in full_text:
            meta_desc = f"Văn bản: {title}\nLoại văn bản: {doc_type}\nKý hiệu: {official_num}\nNgày ban hành: {issued_date}\nCơ quan ban hành: {issuing_org}\nTrạng thái: {status_val}\nURL: {url}"
            full_text = meta_desc

        relations = {}
        if schema_html and "404 -" not in schema_html:
            schema_soup = BeautifulSoup(schema_html, "html.parser")
            for block in schema_soup.find_all(class_="luocdo"):
                t_el = block.find(class_="title")
                rel_title = t_el.get_text(strip=True) if t_el else ""
                links = [f"https://vbpl.vn{a['href'].strip()}" for a in block.find_all("a", class_="jTips") if a.get("href")]
                if rel_title and links:
                    relations[rel_title] = links

        item_id_match = re.search(r"ItemID=(\d+)", url, re.IGNORECASE) or re.search(r"--([a-zA-Z0-9_-]+)$", url)
        source_id = item_id_match.group(1) if item_id_match else str(abs(hash(url)))

        return LegalDocumentSchema(
            source_id=source_id,
            source="vbpl.vn",
            url=url,
            title=title,
            document_type=doc_type,
            official_number=official_num,
            issued_date=issued_date,
            effective_date=atts.get("Ngày có hiệu lực", ""),
            expiry_date=atts.get("Ngày hết hiệu lực", ""),
            issuing_body=issuing_org,
            status=status_val,
            full_text=full_text,
            html_text=html_content,
            attributes=atts,
            relations=relations
        )

    def fetch_with_playwright(self, url: str) -> Optional[str]:
        """Renders Next.js dynamic client-side content with Playwright stealth browser context."""
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    locale="vi-VN",
                    extra_http_headers={
                        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
                    }
                )
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                
                # Hide footer, header, nav elements to get clean document body
                full_html = page.evaluate("""() => {
                    const selectorsToHide = ['footer', 'header', 'nav', '.Footer_wrapMainFooter__e_pgb'];
                    selectorsToHide.forEach(s => {
                        document.querySelectorAll(s).forEach(el => el.remove());
                    });
                    return document.documentElement.outerHTML;
                }""")
                browser.close()
                return full_html
        except Exception as e:
            logger.warning(f"[VBPL Playwright] Error rendering {url}: {e}")
            return None

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        if not is_valid_vbpl_legal_url(url):
            logger.info(f"[VBPL] Discarded non-legal document URL: {url}")
            return None

        # Try static fetch first
        res = self.fetch_page(url)
        html_text = ""
        if res:
            status = getattr(res, "status_code", getattr(res, "status", 200))
            if status == 404:
                return None
            html_text = res.body.decode("utf-8", errors="ignore") if hasattr(res, "body") else (res.text if hasattr(res, "text") else str(res))

        doc = None
        if html_text:
            doc = self.parse_document_from_html(
                url=url,
                html_content=html_text,
                attr_html="",
                schema_html=""
            )

        # If static doc is None or full_text is just loading shell placeholder (< 1000 chars), fallback to Playwright rendering
        if not doc or not doc.full_text or len(doc.full_text) < 1000 or "Đang tải dữ liệu" in doc.full_text:
            logger.info(f"[VBPL] Static HTML incomplete for {url}. Launching Playwright stealth renderer...")
            rendered_html = self.fetch_with_playwright(url)
            if rendered_html:
                pw_doc = self.parse_document_from_html(
                    url=url,
                    html_content=rendered_html,
                    attr_html="",
                    schema_html=""
                )
                if pw_doc and len(pw_doc.full_text) >= 1000:
                    return pw_doc

        return doc
