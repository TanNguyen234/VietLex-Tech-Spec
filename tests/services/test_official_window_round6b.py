"""Round-6b official-source fixes: a deep read keeps the strongest page with its preceding heading and inspects
the neighbours of its strongest probes; registry reader hints steer the deep reader's question; the 2014
real-estate business law is superseded by the 2023 law from 01/01/2025 (Điều 82 khoản 2 of 29/2023/QH15)."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.instrument_registry import assess_expected_instruments, drop_superseded_contexts


def _pdf_with_pages(page_texts):
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
        stream.set_data(b"BT /F1 12 Tf 20 350 Td (" + value.encode("ascii", errors="replace") + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_deep_window_keeps_clause_next_to_strongest_probe_and_its_heading():
    from app.services import official_document_reader as reader

    # 60 pages: the spread probes are 1, 4, 7, 10, 13, 17, 20, 23, ... so page 21 is never probed.
    pages = ["noi dung khac"] * 60
    pages[19] = "Dieu 27. Quyen chuyen doi, chuyen nhuong quyen su dung dat"
    pages[20] = "3. Viec cong chung, chung thuc hop dong chuyen nhuong quyen su dung dat."
    question = "mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?"

    result, _ = reader._smart_window(_pdf_with_pages(pages), question, False, 20, deep_read=True)

    retained = {page["page"]: page["text"] for page in result["pages"]}
    assert 21 in retained
    assert "Viec cong chung" in retained[21]
    assert 20 in retained
    assert len(result["inspected_pages"]) <= reader.DEEP_INSPECTION_LIMIT


def test_strongest_window_contains_the_best_page_and_its_heading():
    from app.services.official_document_reader import _strongest_window

    start = _strongest_window(63, 20, {21: 30, 24: 12, 5: 12, 50: 4})

    assert start <= 20 <= start + 19
    assert start <= 21 <= start + 19


def test_assessment_carries_reader_hint_for_missing_notary_and_land_instruments():
    result = assess_expected_instruments("mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?", [])

    assert "công chứng, chứng thực hợp đồng chuyển nhượng quyền sử dụng đất" in result.reader_hint
    assert "giao dịch phải công chứng" in result.reader_hint


@pytest.mark.asyncio
async def test_registry_reader_hint_steers_the_deep_reader_question():
    from app.services.deep_official_search import search_and_read
    from app.services.runtime_errors import SourceReadError

    class OneHitProvider:
        async def search(self, query, limit=8):
            record = SimpleNamespace(
                url="https://congbao.chinhphu.vn/van-ban/luat-so-46-2024-qh15-43574.htm",
                title="Luật Công chứng 46/2024/QH15",
                snippet="",
                document_number="46/2024/QH15",
            )
            return SimpleNamespace(results=(record,), errors=())

    asked = []

    async def reader(url, **kwargs):
        asked.append(kwargs["question"])
        raise SourceReadError("source_fetch_failed")

    await search_and_read(
        "mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?",
        settings=SimpleNamespace(),
        providers=[OneHitProvider()],
        reader=reader,
        explicit_queries=("Luật Công chứng 46/2024/QH15",),
        explicit_topics=("cong chung",),
        reader_hint="giao dịch phải công chứng",
    )

    assert asked
    assert "giao dịch phải công chứng" in asked[0]


def test_real_estate_business_law_2014_is_superseded_unless_the_question_names_2014():
    old_header = "66/2014/QH13, Điều 17. Hợp đồng kinh doanh bất động sản"
    new_header = "29/2023/QH15, Điều 17. Trách nhiệm của chủ đầu tư dự án bất động sản"
    context_old = f"[{old_header}]\nNguồn: https://example.invalid/van-ban\nTiêu đề: Luật Kinh doanh bất động sản\nĐiều 17."
    context_new = f"[{new_header}]\nNguồn: https://example.invalid/van-ban\nTiêu đề: Luật Kinh doanh bất động sản 2023\nĐiều 17."
    question = "mua bán quyền sử dụng đất có buộc phải công chứng hợp đồng không?"

    kept, dropped = drop_superseded_contexts(question, [context_old, context_new])
    assert kept == [context_new]
    assert sum(dropped.values()) == 1

    kept_2014, dropped_2014 = drop_superseded_contexts(question + " Luật kinh doanh bất động sản 2014", [context_old])
    assert kept_2014 == [context_old]
    assert dropped_2014 == {}
