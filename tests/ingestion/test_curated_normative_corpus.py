from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata, chunk_document
from app.ingestion.structural_index import StructuralRecord
from app.ingestion.vertex_qdrant_migration import (
    VertexQdrantContract,
    build_vertex_point,
)


def _doc(
    document_id: int,
    document_number: str,
    title: str,
    legal_type: str,
    issuing_authority: str,
    issuance_date: str | None,
    content: str,
    *,
    source_url: str | None = None,
    quality_flags: tuple[str, ...] = (),
    sha_override: str | None = None,
) -> StoredDocument:
    digest = sha_override or hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StoredDocument(
        metadata=DocumentMetadata(
            document_id=document_id,
            document_number=document_number,
            title=title,
            source_url=source_url if source_url is not None else f"https://vbpl.vn/{document_id}",
            legal_type=legal_type,
            legal_sectors="Tổng hợp",
            issuing_authority=issuing_authority,
            issuance_date=issuance_date,
        ),
        content=content,
        content_sha256=digest,
        content_store_key=str(document_id),
        quality_flags=quality_flags,
    )


class _FakeContentStore:
    def __init__(self, docs: list[StoredDocument]) -> None:
        self._docs = {doc.metadata.document_id: doc for doc in docs}

    def iter_document_ids(self, *, after_id: int, limit: int) -> list[int]:
        ids = [doc_id for doc_id in sorted(self._docs) if doc_id > after_id]
        return ids[:limit]

    def get_many(self, document_ids: list[int]) -> dict[int, StoredDocument]:
        return {doc_id: self._docs[doc_id] for doc_id in document_ids if doc_id in self._docs}


def test_legal_text_parses_markdown_headings_and_vietnamese_d_article_suffix() -> None:
    meta = DocumentMetadata(
        document_id=101,
        document_number="38/2019/QH14",
        title="Luật thử nghiệm định dạng",
        source_url="https://vbpl.vn/101",
        legal_type="Luật",
        legal_sectors="Thuế",
        issuing_authority="Quốc hội",
        issuance_date="2019-06-13",
    )
    body = (
        "## Chương I\n"
        "QUY ĐỊNH CHUNG\n"
        "### Mục 1\n"
        "**Điều 5đ. Quy định bổ sung đặc thù**\n"
        "1. Người nộp thuế thực hiện kê khai điện tử.\n"
        "2. Trường hợp bất khả kháng thì được gia hạn.\n"
        "   ### Điều 6. Trách nhiệm cơ quan thuế\n"
        "Hướng dẫn người nộp thuế đầy đủ."
    )

    chunks = chunk_document(
        meta,
        body,
        max_tokens=320,
        overlap_tokens=32,
        preserve_article_max_tokens=320,
    )

    assert [c.article for c in chunks] == ["Điều 5đ", "Điều 6"]
    assert "Chương I > Mục 1 > Điều 5đ" == chunks[0].heading_path
    assert "Trường hợp bất khả kháng" in chunks[0].text
    assert chunks[0].clause is None


def test_select_curated_normative_ids_enforces_tiers_parity_and_uncapped_codes() -> None:
    from app.ingestion.curated_normative_corpus import (
        build_curated_structural_records,
        select_curated_normative_ids,
    )

    blds_body = "\n".join(
        f"Điều {i}. Quy định dân sự thứ {i}\n1. Nội dung điều khoản {i}.\n2. Ngoại lệ áp dụng tại điều {i}."
        for i in range(1, 690)
    )
    nd168_body = "\n".join(
        f"Điều {i}. Xử phạt hành vi giao thông thứ {i}\n1. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng."
        for i in range(1, 56)
    )
    tariff_body = "\n".join(
        f"Điều {i}. Biểu thuế dòng {i}\n" + ("mã hàng HS thuế suất ưu đãi " * 45)
        for i in range(1, 45)
    )
    circular_body = "\n".join(
        f"Điều {i}. Hướng dẫn nghiệp vụ {i}\n" + ("quy trình biểu mẫu kế toán chi tiết " * 45)
        for i in range(1, 35)
    )

    docs = [
        _doc(
            665872,
            "52/VBHN-VPQH",
            "Văn bản hợp nhất 52/VBHN-VPQH năm 2025 hợp nhất Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam",
            "Văn bản hợp nhất",
            "Văn phòng quốc hội",
            "2025-07-21",
            "Điều 1. Nước Cộng hòa xã hội chủ nghĩa Việt Nam.\nĐiều 2. Nhà nước pháp quyền.",
        ),
        _doc(
            655275,
            "203/2025/QH15",
            "Nghị quyết 203/2025/QH15 sửa đổi Hiến pháp nước Cộng hòa xã hội chủ nghĩa Việt Nam",
            "Nghị quyết",
            "Quốc hội",
            "2025-06-16",
            "Điều 1. Sửa đổi một số điều của Hiến pháp.\nĐiều 2. Hiệu lực thi hành.",
        ),
        _doc(
            215627,
            "Khongso",
            "Hiến pháp 2013",
            "Hiến pháp",
            "Quốc hội",
            "2013-11-28",
            "Điều 1. Nước Cộng hòa xã hội chủ nghĩa Việt Nam.",
        ),
        _doc(
            296215,
            "91/2015/QH13",
            "Bộ luật dân sự 2015",
            "Luật",
            "Quốc hội",
            "2015-11-24",
            blds_body,
        ),
        _doc(
            675268,
            "108/2025/QH15",
            "Luật Quản lý thuế 2025",
            "Luật",
            "Quốc hội",
            "2025-12-10",
            "Điều 1. Phạm vi điều chỉnh quản lý thuế.\nĐiều 2. Đối tượng áp dụng.",
        ),
        _doc(
            387595,
            "38/2019/QH14",
            "Luật Quản lý thuế 2019",
            "Luật",
            "Quốc hội",
            "2019-06-13",
            "THE NATIONAL ASSEMBLY | SOCIALIST REPUBLIC OF VIETNAM\nLAW ON TAX ADMINISTRATION\nArticle 1. Scope of regulation.",
        ),
        _doc(
            451159,
            "33/VBHN-BTC",
            "Văn bản hợp nhất 33/VBHN-BTC hướng dẫn giao dịch điện tử trong lĩnh vực thuế",
            "Văn bản hợp nhất",
            "Bộ Tài chính",
            "2020-08-06",
            "Điều 1. Phạm vi điều chỉnh.",
        ),
        _doc(
            619502,
            "168/2024/NĐ-CP",
            "Nghị định 168/2024/NĐ-CP quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông đường bộ",
            "Nghị định",
            "Chính phủ",
            "2024-12-26",
            nd168_body,
        ),
        _doc(
            665866,
            "293/2025/NĐ-CP",
            "Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu đối với người lao động làm việc theo hợp đồng lao động",
            "Nghị định",
            "Chính phủ",
            "2025-11-10",
            "Điều 1. Phạm vi.\nĐiều 3. Mức lương tối thiểu vùng.",
        ),
        _doc(
            603278,
            "74/2024/NĐ-CP",
            "Nghị định 74/2024/NĐ-CP quy định về mức lương tối thiểu đối với người lao động",
            "Nghị định",
            "Chính phủ",
            "2024-06-30",
            "Điều 1. Phạm vi.\nĐiều 3. Mức lương tối thiểu.",
        ),
        _doc(
            479312,
            "12/2022/NĐ-CP",
            "Nghị định 12/2022/NĐ-CP xử phạt vi phạm hành chính lĩnh vực lao động, bảo hiểm xã hội",
            "Nghị định",
            "Chính phủ",
            "2022-01-17",
            "Điều 1. Phạm vi.\nĐiều 17. Vi phạm quy định về tiền lương.",
        ),
        _doc(
            321973,
            "131/2016/NĐ-CP",
            "Nghị định 131/2016/NĐ-CP về Biểu thuế nhập khẩu ưu đãi đặc biệt",
            "Nghị định",
            "Chính phủ",
            "2016-09-01",
            tariff_body,
        ),
        _doc(
            665865,
            "110/2025/UBTVQH15",
            "Nghị quyết 110/2025/UBTVQH15 điều chỉnh mức giảm trừ gia cảnh của thuế thu nhập cá nhân",
            "Nghị quyết",
            "Uỷ ban Thường vụ Quốc hội",
            "2025-10-17",
            "Điều 1. Mức giảm trừ gia cảnh.\nĐiều 2. Hiệu lực thi hành.",
        ),
        _doc(
            599999,
            "15/2024/NQ-HĐND",
            "Nghị quyết 15/2024/NQ-HĐND về ngân sách tỉnh Sơn La",
            "Nghị quyết",
            "Tỉnh Sơn La",
            "2024-07-01",
            "Điều 1. Dự toán ngân sách địa phương.",
        ),
        _doc(
            663315,
            "51/2025/TT-BTC",
            "Thông tư 51/2025/TT-BTC quy định thủ tục giao dịch điện tử",
            "Thông tư",
            "Bộ Tài chính",
            "2025-06-24",
            circular_body,
        ),
        _doc(
            700001,
            "01/2024/TT-BTC",
            "Thông tư lỗi mã hóa",
            "Thông tư",
            "Bộ Tài chính",
            "2024-01-02",
            "Điều 1. Nội dung.",
            quality_flags=("encoding_damage",),
        ),
    ]

    store = _FakeContentStore(docs)
    plan = select_curated_normative_ids(store)
    selected_ids = set(plan.document_ids)

    # Required inclusions
    assert {665872, 655275, 215627, 296215, 675268, 619502, 665866, 603278, 479312, 321973, 665865, 663315} <= selected_ids
    # Required exclusions: English untranslated, non-constitutional VBHN, provincial NQ, quality-flagged
    assert 387595 not in selected_ids
    assert 451159 not in selected_ids
    assert 599999 not in selected_ids
    assert 700001 not in selected_ids

    by_id = {entry.document_id: entry for entry in plan.entries}
    # BLDS 2015 keeps all 689 articles uncapped
    assert by_id[296215].distinct_article_count == 689
    assert by_id[296215].chunk_count >= 689
    assert by_id[296215].max_chunks_cap is None

    # NĐ 168/2024 keeps all 55 articles uncapped
    assert by_id[619502].distinct_article_count == 55
    assert by_id[619502].max_chunks_cap is None

    # Tariff decree capped at 24, Circular capped at 20
    assert by_id[321973].chunk_count == 24
    assert by_id[663315].chunk_count == 20

    # Validity hints
    assert by_id[603278].validity_hint == "superseded"
    assert by_id[665866].validity_hint == "active_candidate"
    assert by_id[665872].tier == "A"

    # Build structural records matches plan.total_points and 1:1 document_id set
    records_with_extra = build_curated_structural_records(
        store,
        plan,
        repository="vohuutridung/vietnamese-legal-documents",
        revision="rev-test",
    )
    assert len(records_with_extra) == plan.total_points
    assert {rec.document_id for rec, _ in records_with_extra} == selected_ids


def test_build_vertex_point_preserves_default_and_attaches_optional_extra_payload() -> None:
    contract = VertexQdrantContract()
    record = StructuralRecord(
        record_id="12345678-1234-5678-1234-567812345678",
        body="Điều 3. Mức lương tối thiểu vùng.",
        document_id=665866,
        document_number="293/2025/NĐ-CP",
        title="Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu",
        source_url="https://vbpl.vn/665866",
        legal_type="Nghị định",
        issuing_authority="Chính phủ",
        issuance_date="2025-11-10",
        article="Điều 3",
        clause=None,
        heading_path="Điều 3",
        citation="293/2025/NĐ-CP, Điều 3",
        token_count=7,
        dataset_revision="rev",
        content_sha256="a" * 64,
        chunk_sha256="b" * 64,
    )
    sparse = SimpleNamespace(indices=[1, 5], values=[0.4, 0.9])

    default_point = build_vertex_point(
        record,
        dense_vector=[1.0] + [0.0] * 1023,
        sparse_vector=sparse,
        contract=contract,
    )
    assert "issuance_year" not in default_point.payload
    assert "validity_hint" not in default_point.payload

    enriched_point = build_vertex_point(
        record,
        dense_vector=[1.0] + [0.0] * 1023,
        sparse_vector=sparse,
        contract=contract,
        extra_payload={
            "issuance_year": 2025,
            "normative_rank": 2,
            "validity_hint": "active_candidate",
        },
    )
    assert enriched_point.payload["issuance_year"] == 2025
    assert enriched_point.payload["normative_rank"] == 2
    assert enriched_point.payload["validity_hint"] == "active_candidate"


def test_long_decree_with_annexes_keeps_all_articles_uncapped_and_caps_only_annex_tail() -> None:
    from app.ingestion.curated_normative_corpus import (
        pack_article_clause_chunks,
        select_and_chunk_curated_corpus,
    )

    # 68 substantive Điều articles + huge unnumbered annex tail (> 300 raw chunks)
    articles_part = "\n".join(
        f"Điều {i}. Quy định đăng ký đất đai thứ {i}\n1. Trình tự thực hiện thủ tục tại điều {i}."
        for i in range(1, 69)
    )
    annex_tail = "Phụ lục I\n" + "\n\n".join(
        f"Mẫu số {j:02d}/ĐK: " + ("thông tin biểu mẫu kê khai đăng ký biến động đất đai " * 55)
        for j in range(1, 140)
    )
    nd101 = _doc(
        599101,
        "101/2024/NĐ-CP",
        "Nghị định 101/2024/NĐ-CP quy định về điều tra cơ bản đất đai, đăng ký, cấp Giấy chứng nhận",
        "Nghị định",
        "Chính phủ",
        "2024-07-29",
        articles_part + "\n" + annex_tail,
    )
    nq29_body = "\n".join(
        f"Điều {i}. Quy chế làm việc thứ {i}\n" + ("nội dung chi tiết phiên họp ủy ban thường vụ " * 35)
        for i in range(1, 98)
    )
    nq29 = _doc(
        599029,
        "29/2022/UBTVQH15",
        "Nghị quyết 29/2022/UBTVQH15 ban hành Quy chế làm việc",
        "Nghị quyết",
        "Ủy ban Thường vụ Quốc hội",
        "2022-12-12",
        nq29_body,
    )

    plan, prepared = select_and_chunk_curated_corpus(_FakeContentStore([nd101, nq29]))
    by_id = {e.document_id: e for e in plan.entries}

    _, _, nd101_chunks = prepared[599101]
    retained_nd101_articles = {c.article for c in nd101_chunks if c.article}
    assert len(retained_nd101_articles) == 68
    assert by_id[599101].distinct_article_count == 68
    assert sum(1 for c in nd101_chunks if c.article is None) <= 16

    _, _, nq29_chunks = prepared[599029]
    retained_nq29_articles = {c.article for c in nq29_chunks if c.article}
    assert len(retained_nq29_articles) == 97
    assert by_id[599029].distinct_article_count == 97

    # Nit N-1: article_number == clause_number ("Điều 2" + clause "2") must not repeat article header
    meta2 = DocumentMetadata(
        document_id=202,
        document_number="01/2025/QH15",
        title="Luật thử nghiệm",
        source_url="https://vbpl.vn/202",
        legal_type="Luật",
        legal_sectors="Chung",
        issuing_authority="Quốc hội",
        issuance_date="2025-01-01",
    )
    long_c1 = "1. " + ("đối tượng áp dụng chi tiết " * 25)
    short_c2 = "2. Cơ quan tổ chức cá nhân có liên quan."
    raw_c = chunk_document(
        meta2,
        f"Điều 2. Đối tượng áp dụng\n{long_c1}\n{short_c2}",
        max_tokens=320,
        overlap_tokens=32,
        preserve_article_max_tokens=100,
    )
    packed_c = pack_article_clause_chunks(raw_c, max_tokens=320)
    assert len(packed_c) == 1
    assert packed_c[0].text.count("Điều 2. Đối tượng áp dụng") == 1


def test_pre_2013_constitutions_and_replaced_statutes_marked_superseded_and_spec_windows() -> None:
    from app.ingestion.curated_normative_corpus import select_curated_normative_ids

    docs = [
        _doc(36948, "Khongso", "Hiến pháp năm 1980", "Hiến pháp", "Quốc hội", "1980-12-18", "Điều 1. Nhà nước."),
        _doc(1002008, "23/2008/QH12", "Luật Giao thông đường bộ 2008", "Luật", "Quốc hội", "2008-11-13", "Điều 1. Phạm vi."),
        _doc(1002014, "65/2014/QH13", "Luật Nhà ở 2014", "Luật", "Quốc hội", "2014-11-25", "Điều 1. Phạm vi."),
        _doc(1002005, "51/2005/QH11", "Luật Giao dịch điện tử 2005", "Luật", "Quốc hội", "2005-11-29", "Điều 1. Phạm vi."),
        _doc(1001999, "13/1999/QH10", "Luật Doanh nghiệp nhà nước 1999", "Luật", "Quốc hội", "1999-06-12", "Điều 1. Phạm vi."),
        _doc(1002015, "59/2015/NĐ-CP", "Nghị định 59/2015/NĐ-CP về quản lý dự án đầu tư xây dựng", "Nghị định", "Chính phủ", "2015-06-18", "Điều 1. Phạm vi."),
        _doc(1002016, "97/2015/QH13", "Nghị quyết 97/2015/QH13", "Nghị quyết", "Quốc hội", "2015-11-26", "Điều 1. Nội dung."),
    ]
    plan = select_curated_normative_ids(_FakeContentStore(docs))
    by_id = {e.document_id: e for e in plan.entries}

    # Spec windows: 1995-2026 Laws (Tier A), 2015-2026 Decrees (Tier B) & Central Resolutions (Tier D)
    assert by_id[1001999].tier == "A"
    assert by_id[1002015].tier == "B"
    assert by_id[1002016].tier == "D"

    # Repealed pre-2013 constitutions & replaced 2005-2014 statutes must be marked superseded
    assert by_id[36948].validity_hint == "superseded"
    assert by_id[1002008].validity_hint == "superseded"
    assert by_id[1002014].validity_hint == "superseded"
    assert by_id[1002005].validity_hint == "superseded"
