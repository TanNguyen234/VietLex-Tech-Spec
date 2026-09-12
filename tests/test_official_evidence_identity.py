def test_official_quote_identity_tracks_document_version_not_page_window():
    from app.services.trusted_source_reader import official_evidence_id
    source = {"url": "https://vanban.chinhphu.vn/?docid=219431", "document_sha256": "a" * 64, "sha256": "b" * 64}
    first = official_evidence_id(source, "Cùng một trích đoạn")
    assert len(first) == 24
    assert first == official_evidence_id({**source, "sha256": "c" * 64, "page_start": 2}, "Cùng một trích đoạn")
    assert first != official_evidence_id({**source, "document_sha256": "d" * 64}, "Cùng một trích đoạn")
    assert first != official_evidence_id(source, "Một trích đoạn khác")
    html = {"url": source["url"], "sha256": "b" * 64}
    assert official_evidence_id(html, "Câu") != official_evidence_id({**html, "sha256": "c" * 64}, "Câu")
