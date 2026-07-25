import pytest
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler

def test_vietlaw_crawler_parser():
    crawler = VietlawCrawler(use_stealth=False)
    mock_html = """
    <html>
        <body>
            <div class="document-detail">
                <h1 class="doc-title">Luật Ban hành văn bản quy phạm pháp luật</h1>
                <div class="doc-number">Số: 80/2015/QH13</div>
                <div class="doc-content">
                    <p>Điều 1. Phạm vi điều chỉnh quy định về việc xây dựng, ban hành văn bản...</p>
                </div>
            </div>
        </body>
    </html>
    """
    doc = crawler.parse_document_from_html("https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID=999", mock_html)
    assert doc.source == "vietlaw.quochoi.vn"
    assert doc.title == "Luật Ban hành văn bản quy phạm pháp luật"
    assert doc.official_number == "80/2015/QH13"
    assert "Điều 1. Phạm vi điều chỉnh" in doc.full_text
