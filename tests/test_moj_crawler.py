import pytest
from app.ingestion.crawlers.moj_crawler import MOJCrawler

def test_moj_crawler_parser():
    crawler = MOJCrawler(use_stealth=False)
    mock_html = """
    <html>
        <body>
            <div class="portlet-content">
                <h2 class="article-title">Thông tư 05/2024/TT-BTP hướng dẫn công tác tư pháp</h2>
                <div class="article-date">Ngày đăng: 15/05/2024</div>
                <div class="article-body">
                    <p>Bộ Tư pháp ban hành thông tư chi tiết hướng dẫn thi hành...</p>
                </div>
            </div>
        </body>
    </html>
    """
    doc = crawler.parse_document_from_html("https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID=888", mock_html)
    assert doc.source == "moj.gov.vn"
    assert doc.title == "Thông tư 05/2024/TT-BTP hướng dẫn công tác tư pháp"
    assert doc.issued_date == "15/05/2024"
    assert "Bộ Tư pháp ban hành thông tư" in doc.full_text
