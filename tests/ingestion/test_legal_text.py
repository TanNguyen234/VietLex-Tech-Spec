import importlib

import pytest


def _legal_text_module():
    return importlib.import_module("app.ingestion.legal_text")


def _metadata():
    legal_text = _legal_text_module()
    return legal_text.DocumentMetadata(
        document_id=42,
        document_number="12/2026/NĐ-CP",
        title="Nghị định thử nghiệm",
        source_url="https://example.invalid/42",
        legal_type="Nghị định",
        legal_sectors="Hành chính",
        issuing_authority="Chính phủ",
        issuance_date="2026-01-02",
    )


def test_article_chunk_preserves_heading_ancestry_and_citation() -> None:
    legal_text = _legal_text_module()
    text = (
        "Chương I\n"
        "QUY ĐỊNH CHUNG\n"
        "Điều 1. Phạm vi\n"
        "1. Nội dung thứ nhất.\n"
        "2. Nội dung thứ hai."
    )

    chunks = legal_text.chunk_document(
        _metadata(),
        text,
        max_tokens=40,
        overlap_tokens=5,
    )

    assert chunks[0].article == "Điều 1"
    assert "Chương I" in chunks[0].heading_path
    assert chunks[0].citation.startswith("12/2026/NĐ-CP, Điều 1")
    assert "Nguồn: https://example.invalid/42" in chunks[0].formatted_context()


def test_article_is_split_at_clause_boundaries_without_cross_clause_overlap() -> None:
    legal_text = _legal_text_module()
    text = (
        "Điều 7. Điều kiện cấp phép\n"
        "1. Người đề nghị phải nộp hồ sơ hợp lệ.\n"
        "2. Cơ quan có thẩm quyền trả lời bằng văn bản."
    )

    chunks = legal_text.chunk_document(
        _metadata(),
        text,
        max_tokens=40,
        overlap_tokens=5,
    )

    assert [chunk.clause for chunk in chunks] == ["1", "2"]
    assert all(chunk.article == "Điều 7" for chunk in chunks)
    assert "Cơ quan có thẩm quyền" not in chunks[0].text
    assert "Người đề nghị" not in chunks[1].text
    assert chunks[0].citation.endswith("Điều 7, Khoản 1")
    assert chunks[1].citation.endswith("Điều 7, Khoản 2")


def test_oversized_clause_uses_bounded_windows_with_the_same_citation() -> None:
    legal_text = _legal_text_module()
    text = "Điều 8. Nghĩa vụ\n1. " + "nghĩa vụ pháp lý " * 80

    chunks = legal_text.chunk_document(
        _metadata(),
        text,
        max_tokens=30,
        overlap_tokens=4,
    )

    assert len(chunks) > 1
    assert {chunk.clause for chunk in chunks} == {"1"}
    assert all(chunk.citation.endswith("Điều 8, Khoản 1") for chunk in chunks)
    assert all(0 < chunk.token_count <= 30 for chunk in chunks)


def test_paragraph_fallback_is_bounded_and_nonempty() -> None:
    legal_text = _legal_text_module()
    text = "\n\n".join(
        f"Đoạn văn hành chính số {index} có nội dung."
        for index in range(80)
    )

    chunks = legal_text.chunk_document(
        _metadata(),
        text,
        max_tokens=30,
        overlap_tokens=5,
    )

    assert len(chunks) > 1
    assert all(0 < chunk.token_count <= 30 for chunk in chunks)


def test_dense_text_and_point_id_are_deterministic_and_bounded() -> None:
    legal_text = _legal_text_module()
    text = "Điều 1. A\n" + ("nội dung " * 10_000) + "\nĐiều 99. Z"

    first = legal_text.build_dense_text(
        _metadata(),
        text,
        max_tokens=256,
    )
    second = legal_text.build_dense_text(
        _metadata(),
        text,
        max_tokens=256,
    )

    assert first == second
    assert len(first.split()) <= 256
    assert legal_text.deterministic_point_id(
        "repo",
        "revision",
        42,
    ) == legal_text.deterministic_point_id("repo", "revision", 42)


def test_dense_text_prioritizes_structural_outline_before_body() -> None:
    legal_text = _legal_text_module()
    text = (
        "Điều 1. Phạm vi điều chỉnh\n"
        + ("nội dung mở rộng " * 200)
        + "\nĐiều 99. Điều khoản thi hành"
    )

    dense = legal_text.build_dense_text(
        _metadata(),
        text,
        max_tokens=180,
        max_characters=2_000,
    )

    assert dense.index("Mục lục cấu trúc") < dense.index("Nội dung đại diện")
    assert "Điều 99" in dense
    assert len(dense.split()) <= 180


def test_retrieval_text_can_skip_redundant_content_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legal_text = _legal_text_module()

    def fail_if_called(_: str) -> str:
        raise AssertionError("content is already normalized in the store")

    monkeypatch.setattr(
        legal_text,
        "normalize_legal_text",
        fail_if_called,
    )

    dense = legal_text.build_dense_text(
        _metadata(),
        "Điều 1. Nội dung đã chuẩn hóa.",
        content_is_normalized=True,
    )
    sparse = legal_text.build_sparse_text(
        _metadata(),
        "Điều 1. Nội dung đã chuẩn hóa.",
        content_is_normalized=True,
    )

    assert dense
    assert sparse
