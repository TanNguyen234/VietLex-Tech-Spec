import re
import requests
from typing import Optional
from scrapling import Selector
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

class VietlawCrawler(BaseLegalCrawler):
    def parse_document_from_html(self, url: str, html_content: str) -> Optional[LegalDocumentSchema]:
        # Pre-process HTML with BeautifulSoup to strip script/style and SharePoint ASP.NET boilerplate tags
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer"]):
            tag.extract()
        for el in soup.select("#s4-ribbonrow, .s4-skipribbonshortcut, .ms-nav"):
            el.extract()
        clean_html = str(soup)
        page = Selector(clean_html)
        
        # Check if page is invalid or cookie challenge page
        if len(html_content) < 1000 and "document.cookie=" in html_content and "window.location.reload" in html_content:
            return None

        # Select title from headings, CSS selectors, or page title
        title_nodes = page.css(".doc-title::text", "h1::text", ".title::text", ".vbpq-title::text", ".TextTitle::text").getall()
        title = title_nodes[0].strip() if title_nodes else ""
        if not title:
            title_tag = page.css("title::text").getall()
            if title_tag:
                title = title_tag[0].replace("Cơ sở dữ liệu Luật Việt Nam - VietLaw", "").replace("Văn bản Luật Việt Nam", "").strip()
        if not title:
            title = "Văn bản Luật Việt Nam"

        # Content cleaning targeting .toanvan main document text container
        content_nodes = page.css(".toanvan ::text", ".doc-content ::text", "#content ::text", ".main-content ::text").getall()
        if content_nodes:
            full_text = " ".join(" ".join(content_nodes).split()).strip()
        else:
            texts = page.css("body ::text").getall()
            full_text = " ".join(" ".join(texts).split()).strip()

        # Official number
        num_nodes = page.css(".doc-number::text", ".number::text", ".vbpq-number::text").getall()
        num_text = num_nodes[0].strip() if num_nodes else ""
        official_number = re.sub(r"^Số:\s*", "", num_text)
        if not official_number:
            match = re.search(r"([0-9]+/[0-9]{4}/[A-Z0-9-]+|[0-9]+/[0-9]{2}/[A-Z0-9-]+)", title)
            if match:
                official_number = match.group(1)
        if not official_number and full_text:
            match = re.search(r"(?:Luật|Nghị định|Quyết định|Thông tư|Số)\s*số:\s*([0-9]+/[0-9]{4}/[A-Z0-9-]+|[0-9]+/[0-9]{2}/[A-Z0-9-]+)", full_text, re.IGNORECASE)
            if not match:
                match = re.search(r"([0-9]+/[0-9]{4}/[A-Z0-9-]+|[0-9]+/[0-9]{2}/[A-Z0-9-]+)", full_text)
            if match:
                official_number = match.group(1)

        item_id = re.search(r"ItemID=(\d+)", url)
        sid = item_id.group(1) if item_id else "unknown"

        return LegalDocumentSchema(
            source_id=sid,
            source="vietlaw.quochoi.vn",
            url=url,
            title=title,
            official_number=official_number,
            full_text=full_text,
            html_text=html_content
        )

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        try:
            res = requests.get(url, headers=headers, timeout=15, verify=False)
            if len(res.text) > 1000 and "document.cookie=" not in res.text:
                return self.parse_document_from_html(url, res.text)
                
            m = re.search(r'D1N=([a-f0-9]+)', res.text, re.IGNORECASE)
            if m:
                token = m.group(1)
                headers["Cookie"] = f"D1N={token}"
                res = requests.get(url, headers=headers, cookies={"D1N": token}, timeout=15, verify=False)

            return self.parse_document_from_html(url, res.text)
        except Exception:
            return None

