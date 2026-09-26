import hashlib

import pytest


def test_point_preserves_verified_full_document_without_vector():
    from scripts.build_qdrant_full_doc_index import point_from_source

    content = "Điều 1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động."
    row = {
        "document_id": 399861,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "legal_type": "Văn bản hợp nhất",
        "issuing_authority": "Bộ Lao động",
        "issuance_date": "2026-01-01",
    }

    point = point_from_source(row)

    assert point["id"] == 399861
    assert point["vector"] == {}
    assert point["payload"]["body"] == content
    assert point["payload"]["content_sha256"] == row["content_sha256"]
    assert point["payload"]["issuance_date"] == "2026-01-01"


def test_point_rejects_source_hash_mismatch():
    from scripts.build_qdrant_full_doc_index import point_from_source

    with pytest.raises(ValueError, match="source_hash_mismatch"):
        point_from_source({
            "document_id": 1,
            "content": "Điều 1. Nội dung",
            "content_sha256": "0" * 64,
            "legal_type": "Luật",
            "issuing_authority": "Quốc hội",
            "issuance_date": "2026-01-01",
        })
