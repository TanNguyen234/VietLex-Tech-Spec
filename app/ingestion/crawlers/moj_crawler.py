import re
from typing import Optional
from scrapling import Selector
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

class MOJCrawler(BaseLegalCrawler):
    def parse_document_from_html(self, url: str, html_content: str) -> LegalDocumentSchema:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer"]):
            tag.extract()
        clean_html = str(soup)
        page = Selector(clean_html)
        
        title_nodes = page.css(".article-title::text", ".title::text", "h1::text", "h2::text").getall()
        title = title_nodes[0].strip() if title_nodes else ""
        if not title:
            title_tag = page.css("title::text").getall()
            if title_tag:
                title = title_tag[0].split("-")[0].strip()
        if not title:
            title = "Văn bản Bộ Tư pháp"

        official_number = ""
        match = re.search(r"([0-9]+/[0-9]{4}/[A-Z0-9-]+|[0-9]+/[0-9]{2}/[A-Z0-9-]+)", title)
        if match:
            official_number = match.group(1)

        date_nodes = page.css(".article-date::text", ".date::text", ".content-chitiet-tintuc::text").getall()
        date_text = " ".join(date_nodes)
        issued_date_match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", date_text)
        issued_str = issued_date_match.group(0) if issued_date_match else ""

        body_nodes = page.css(".content-noidung ::text", ".news-detail ::text", ".article-body ::text", ".content ::text", ".detail-content ::text").getall()
        if body_nodes:
            body = " ".join(" ".join(body_nodes).split()).strip()
        else:
            texts = page.css("body ::text").getall()
            body = " ".join(" ".join(texts).split()).strip()

        item_id = re.search(r"ItemID=(\d+)", url) or re.search(r"([a-zA-Z0-9]+)\.html$", url)
        sid = item_id.group(1) if item_id else "unknown"

        return LegalDocumentSchema(
            source_id=sid,
            source="moj.gov.vn",
            url=url,
            title=title,
            official_number=official_number,
            issued_date=issued_str,
            full_text=body,
            html_text=html_content
        )

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        res = self.fetch_page(url)
        if not res:
            return None
        return self.parse_document_from_html(url, res.text if hasattr(res, "text") else str(res))
