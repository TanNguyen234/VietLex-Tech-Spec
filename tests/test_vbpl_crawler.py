import pytest
from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler

def test_vbpl_crawler_parse_mock():
    crawler = VBPLCrawler(use_stealth=False)
    url = "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=130000"
    mock_html = """
    <html>
        <body>
            <div class="box-map">
                <a href="#">Trang chủ</a>
                <a href="#">Luật Đất đai 2024</a>
            </div>
            <div class="fulltext">
                <div>Phần đầu văn bản</div>
                <div>Nội dung quy định chi tiết về quản lý và sử dụng đất đai năm 2024...</div>
            </div>
        </body>
    </html>
    """
    mock_attr = """
    <div class="vbProperties">
        <table>
            <tr><td class="label">Số ký hiệu</td><td>31/2024/QH15</td></tr>
            <tr><td class="label">Ngày ban hành</td><td>18/01/2024</td></tr>
            <tr><td class="label">Cơ quan ban hành</td><td>Quốc hội</td></tr>
        </table>
    </div>
    """
    mock_schema = """
    <div class="vbLuocdo">
        <div class="luocdo">
            <div class="title"><a href="#">Văn bản căn cứ</a></div>
            <a class="jTips" href="/tw/Pages/vbpq-todan.aspx?ItemID=100">Hiến pháp 2013</a>
        </div>
    </div>
    """
    doc = crawler.parse_document_from_html(
        url=url,
        html_content=mock_html,
        attr_html=mock_attr,
        schema_html=mock_schema
    )
    assert doc.title == "Luật Đất đai 2024"
    assert doc.official_number == "31/2024/QH15"
    assert doc.issued_date == "18/01/2024"
    assert doc.issuing_body == "Quốc hội"
    assert "Nội dung quy định chi tiết" in doc.full_text
    assert "Văn bản căn cứ" in doc.relations
    assert doc.relations["Văn bản căn cứ"][0] == "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=100"

def test_vbpl_crawler_full_text_length():
    crawler = VBPLCrawler(use_stealth=False)
    url = "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-52-2006-nd-cp-ve-phat-hanh-trai-phieu-doanh-nghiep--16181"
    doc = crawler.parse_document(url)
    assert doc is not None
    assert doc.official_number == "52/2006/NĐ-CP"
    assert len(doc.full_text) > 20000, f"Expected full_text > 20000 chars, got {len(doc.full_text)}"
