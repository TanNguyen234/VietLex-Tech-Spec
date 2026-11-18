from __future__ import annotations

from io import BytesIO
import json
import struct

import pytest
from pypdf import PdfWriter


G7_VALID_STREAM_URL = (
    "https://g7.cdnchinhphu.vn/api/download/stream?"
    "Url=abc_DEF-123~~&file_name=2025_168-2024-ND-CP.pdf"
)


def _text_pdf(page_texts: list[str]) -> bytes:
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for value in page_texts:
        page = writer.add_blank_page(width=300, height=400)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            b"BT /F1 12 Tf 20 350 Td ("
            + value.encode("ascii", errors="replace")
            + b") Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_two_tier_domain_classification():
    from app.services.web_source_tiers import classify_web_source_tier

    # Tier 1: official primary portals
    assert (
        classify_web_source_tier(
            "https://vbpl.moj.gov.vn/vbpq/Lists/Vn%20bn/View_Detail.aspx?ItemID=1"
        )
        == "official_primary"
    )
    assert (
        classify_web_source_tier("https://phapdien.moj.gov.vn/qt/tintuc/Pages/bo-phap-dien.aspx")
        == "official_primary"
    )
    assert classify_web_source_tier("https://moj.gov.vn/vbpq/lists/vn%20bn/view_detail.aspx?itemid=5") == "official_primary"
    assert classify_web_source_tier("https://quochoi.vn/tintuc/Pages/tin-hoat-dong.aspx") == "official_primary"
    assert classify_web_source_tier("https://tandtc.gov.vn/web/guest/van-ban-phap-luat") == "official_primary"
    assert classify_web_source_tier("https://vanban.chinhphu.vn/?docid=212456") == "official_primary"
    assert classify_web_source_tier("https://congbao.chinhphu.vn/van-ban/nghi-dinh-1.htm") == "official_primary"
    assert classify_web_source_tier("https://datafiles.chinhphu.vn/file/168.pdf") == "official_primary"
    assert classify_web_source_tier("https://congbaocdn.chinhphu.vn/file/168.pdf") == "official_primary"
    assert classify_web_source_tier("https://chinhphu.vn/he-thong-van-ban?class_id=1") == "official_primary"
    assert classify_web_source_tier("https://mof.gov.vn/webcenter/portal/btc") == "official_primary"
    assert classify_web_source_tier(G7_VALID_STREAM_URL) == "official_primary"

    # Tier 2: legal discovery pivot only
    assert (
        classify_web_source_tier(
            "https://thuvienphapluat.vn/van-ban/Giao-thong/Nghi-dinh-168-2024-ND-CP.aspx"
        )
        == "legal_discovery_pivot"
    )
    assert (
        classify_web_source_tier(
            "https://www.thuvienphapluat.vn/phap-luat/vuot-den-do-phat-bao-nhieu.html"
        )
        == "legal_discovery_pivot"
    )
    assert (
        classify_web_source_tier(
            "https://luatvietnam.vn/giao-thong/nghi-dinh-168-2024-nd-cp-378123-d1.html"
        )
        == "legal_discovery_pivot"
    )
    assert (
        classify_web_source_tier("https://www.luatvietnam.vn/lao-dong/muc-luong-toi-thieu.html")
        == "legal_discovery_pivot"
    )

    # Untrusted / unsafe / news-or-draft portals
    assert classify_web_source_tier("https://example.com/blog") == "untrusted"
    assert classify_web_source_tier("http://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1") == "untrusted"
    assert classify_web_source_tier("https://u:p@vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1") == "untrusted"
    assert classify_web_source_tier("https://vbpl.vn:8443/TW/Pages/vbpq-toanvan.aspx?ItemID=1") == "untrusted"
    assert classify_web_source_tier("https://vbpl.vn/a", domain="evil.test") == "untrusted"
    assert classify_web_source_tier("https://g7.cdnchinhphu.vn/other/path.pdf") == "untrusted"
    assert classify_web_source_tier("https://xaydungchinhsach.chinhphu.vn/bai-viet.htm") == "untrusted"
    assert classify_web_source_tier("https://baochinhphu.vn/tin-tuc.htm") == "untrusted"
    assert classify_web_source_tier("https://duthaoonline.quochoi.vn/du-thao") == "untrusted"
    assert classify_web_source_tier("https://duthao.moj.gov.vn/Pages/home.aspx") == "untrusted"
    assert classify_web_source_tier("https://gov.vn/") == "untrusted"
    assert classify_web_source_tier("https://moj.gov.vn/qt/cacchuyenmuc/duthao/Pages/default.aspx") == "untrusted"


def test_tier1_allowlist_parity_and_tier2_rejection_in_trusted_reader():
    from app.services.chat_official_supplement import _source_context
    from app.services.deep_research import is_official_source
    from app.services.legal_effect import _is_official_source as is_effect_official_source
    from app.services.trusted_source_reader import validate_source_url

    for tier1_url in (
        "https://vbpl.moj.gov.vn/vbpq/Lists/Vn%20bn/View_Detail.aspx?ItemID=123",
        "https://phapdien.moj.gov.vn/qt/tintuc/Pages/bo-phap-dien.aspx",
        "https://quochoi.vn/vanban/Pages/van-ban-moi.aspx?ItemID=45",
        "https://tandtc.gov.vn/web/guest/nghi-quyet-hdtp",
        "https://mof.gov.vn/webcenter/portal/btc",
    ):
        assert is_official_source(tier1_url) is True
        assert is_effect_official_source(tier1_url) is True
        assert validate_source_url(tier1_url) == tier1_url

    assert is_effect_official_source("https://duthao.moj.gov.vn/Pages/home.aspx") is False
    assert is_effect_official_source("https://gov.vn/") is False

    news_source = {
        "text": "Điều 3. Mức lương tối thiểu vùng.",
        "sha256": "a" * 64,
        "retrieved_at": "2026-11-18T00:00:00+00:00",
        "method": "visible_html_text",
        "title": "Bản tin lương tối thiểu",
    }
    assert _source_context("https://baochinhphu.vn/tin-tuc.htm", news_source, "lương tối thiểu") is None

    for tier2_url in (
        "https://thuvienphapluat.vn/van-ban/Lao-dong/Nghi-dinh-293-2025-ND-CP.aspx",
        "https://luatvietnam.vn/lao-dong/nghi-dinh-293-2025-nd-cp.html",
    ):
        assert is_official_source(tier2_url) is False
        with pytest.raises(ValueError, match="source_origin_not_approved"):
            validate_source_url(tier2_url)
        fake_source = {
            "text": "Điều 3. Mức lương tối thiểu vùng.",
            "sha256": "a" * 64,
            "retrieved_at": "2026-11-18T00:00:00+00:00",
            "method": "visible_html_text",
            "title": "Nghị định 293/2025/NĐ-CP",
        }
        assert _source_context(tier2_url, fake_source, "lương tối thiểu") is None


@pytest.mark.parametrize(
    "non_salary_query",
    [
        "Chủ nguồn thải chất thải nguy hại phải khai báo khối lượng và chất lượng ở đâu?",
        "Số lượng thành viên công ty TNHH hai thành viên tối đa là bao nhiêu?",
        "Quy định về tiết kiệm năng lượng và dung lượng lưu trữ dữ liệu?",
        "Trọng lượng hàng hóa và lưu lượng xả thải vượt mức cho phép?",
        "Lực lượng vũ trang, ước lượng thiệt hại và hàm lượng kim loại nặng?",
        "Các bên thương lượng hợp đồng mua bán hàng hóa không thành?",
        "Đo lượng mưa trung bình trong năm theo quy chuẩn kỹ thuật?",
        "khai bao khoi luong va chat luong chat thai nguy hai o dau",
        "so luong co dong va thuong luong hop dong mua ban",
    ],
)
def test_luong_quantity_compounds_never_trigger_salary_topic(non_salary_query: str):
    from app.services.legal_topic_terms import (
        contains_topic_phrase,
        extract_official_topic_phrases,
    )

    assert "lương" not in extract_official_topic_phrases(non_salary_query, limit=8)
    assert not contains_topic_phrase(non_salary_query, "lương")


@pytest.mark.parametrize(
    "salary_query",
    [
        "Công ty trả 70% lương khi thử việc có đúng không?",
        "luong thu viec toi thieu la bao nhieu phan tram",
        "Khối lượng công việc rất nhiều nhưng công ty nợ lương 3 tháng?",
    ],
)
def test_real_salary_queries_still_match_luong_topic(salary_query: str):
    from app.services.legal_topic_terms import (
        contains_topic_phrase,
        extract_official_topic_phrases,
    )

    assert "lương" in extract_official_topic_phrases(salary_query, limit=8)
    assert contains_topic_phrase(salary_query, "lương")


def test_deep_pdf_worker_output_accepts_up_to_deep_inspection_limit_and_multi_cluster_pages():
    from app.services.official_document_reader import (
        DEEP_INSPECTION_LIMIT,
        DEEP_SMART_WORKER_TIMEOUT_SECONDS,
        SMART_WORKER_TIMEOUT_SECONDS,
        SourceReadError,
        _decode_worker_output,
        _smart_window,
    )

    assert SMART_WORKER_TIMEOUT_SECONDS > 0
    assert DEEP_SMART_WORKER_TIMEOUT_SECONDS >= SMART_WORKER_TIMEOUT_SECONDS

    # 45 inspected pages (> 40, <= DEEP_INSPECTION_LIMIT=48) + non-contiguous clusters in deep_read
    selected_pages = [*range(8, 16), *range(62, 70)]
    inspected_pages = sorted({*selected_pages, *range(1, 38)})
    payload_dict = {
        "page_count": 90,
        "pages": [{"page": p, "text": f"Dieu {p}. Noi dung."} for p in selected_pages],
        "parser_recovered": False,
        "inspected_pages": inspected_pages,
        "smart_selection_status": "probe_match",
        "ocr_input_length": 0,
    }
    encoded = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    stdout = struct.pack("!I", len(encoded)) + encoded

    decoded = _decode_worker_output(stdout, deep_read=True)
    assert [p["page"] for p in decoded["pages"]] == selected_pages
    assert len(decoded["inspected_pages"]) == 45 <= DEEP_INSPECTION_LIMIT

    # Non-deep mode still enforces contiguous <=5 page window and <=10 inspections
    non_deep_bad = {
        "page_count": 20,
        "pages": [{"page": 2, "text": "A"}, {"page": 5, "text": "B"}],
        "parser_recovered": False,
        "inspected_pages": [2, 5],
        "smart_selection_status": "probe_match",
        "ocr_input_length": 0,
    }
    raw_bad = json.dumps(non_deep_bad, separators=(",", ":")).encode("utf-8")
    with pytest.raises(SourceReadError, match="source_processing_output_invalid"):
        _decode_worker_output(struct.pack("!I", len(raw_bad)) + raw_bad, deep_read=False)

    # _smart_window in deep_read extracts distant article clusters (e.g., Dieu 6 on p.10 and Dieu 21 on p.75)
    pages = [f"Dieu {(idx * 22) // 90 + 3}. Noi dung chung." for idx in range(1, 91)]
    pages[9] = "Dieu 6. Xu phat vi pham giao thong vuot den do phat tien 18 trieu."
    pages[70] = "Dieu 20. Tham quyen xu phat."
    pages[74] = "Dieu 21. Tam giu phuong tien vi pham hanh chinh giao thong."
    pages[75] = "Dieu 22. Thu tuc tra lai phuong tien."
    extracted, _ = _smart_window(
        _text_pdf(pages),
        "xử phạt vi phạm tạm giữ [gợi ý điều khoản: 6, 21]",
        False,
        20,
        deep_read=True,
    )
    retained_nums = [p["page"] for p in extracted["pages"]]
    assert 10 in retained_nums
    assert 75 in retained_nums
    assert len(retained_nums) <= 20
    assert len(extracted["inspected_pages"]) <= DEEP_INSPECTION_LIMIT


def test_pack_sources_retains_complete_final_article_but_drops_mid_sentence_cutoff():
    import hashlib
    from datetime import datetime, timezone
    from app.services.deep_official_search import pack_sources
    from app.services.official_search_plan import DEEP_READING, build_official_search_plan

    def make_pdf_source(text: str) -> dict:
        return {
            "url": "https://congbao.chinhphu.vn/van-ban/nghi-dinh-168-1.htm",
            "attachment_url": "https://datafiles.chinhphu.vn/168.pdf",
            "title": "Nghị định 168/2024/NĐ-CP",
            "document_number": "168/2024/NĐ-CP",
            "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "document_sha256": "b" * 64,
            "page_start": 5,
            "page_end": 10,
            "page_count": 60,
            "truncated": True,
            "requires_ocr": False,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "method": "pdf_text",
            "legal_effect_status": "unverified",
        }

    # Complete single-article or final-article ending with sentence punctuation -> RETAINED
    complete_item = make_pdf_source(
        "Điều 6. Xử phạt vi phạm giao thông\n"
        "1. Phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng đối với hành vi vượt đèn đỏ."
    )
    contexts, report = pack_sources(
        [complete_item],
        build_official_search_plan("xử phạt vi phạm 168/2024/NĐ-CP"),
        DEEP_READING,
    )
    assert len(contexts) == 1
    assert "18.000.000 đồng" in contexts[0]
    assert not any(b.get("reason") == "incomplete_article" for b in report["excluded_blocks"])

    # Visibly cut off mid-sentence -> DROPPED as incomplete_article
    cutoff_item = make_pdf_source(
        "Điều 6. Xử phạt vi phạm giao thông\n"
        "1. Phạt tiền từ 18.000.000 đồng đối với hành vi không chấp hành"
    )
    contexts_cut, report_cut = pack_sources(
        [cutoff_item],
        build_official_search_plan("xử phạt vi phạm 168/2024/NĐ-CP"),
        DEEP_READING,
    )
    assert contexts_cut == []
    assert any(b.get("reason") == "incomplete_article" for b in report_cut["excluded_blocks"])
