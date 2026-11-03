from __future__ import annotations

import hashlib
from types import SimpleNamespace


def _document(document_id, document_number, title, content, *, authority="Quốc hội", issued="2022-01-01", digest=None):
    metadata = SimpleNamespace(
        document_id=document_id,
        document_number=document_number,
        title=title,
        source_url=f"https://corpus.example.vn/{document_id}",
        legal_type="Luật",
        legal_sectors="Lao động",
        issuing_authority=authority,
        issuance_date=issued,
    )
    return SimpleNamespace(
        metadata=metadata,
        content=content,
        content_sha256=digest or hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


class _Index:
    def __init__(self, matches):
        self.matches = matches
        self.search_calls = []

    def search(self, query, *, limit):
        self.search_calls.append((query, limit))
        return [
            document_id
            for document_id in self.matches.get(query, [])
        ][:limit]


def _hit(document):
    return SimpleNamespace(
        document_id=document.metadata.document_id,
        document_number=document.metadata.document_number,
        title=document.metadata.title,
        issuing_authority=document.metadata.issuing_authority,
        issuance_date=document.metadata.issuance_date,
    )


class _Browser:
    def __init__(self, matches, documents):
        self.fake_index = _Index(
            {key: [doc.metadata.document_id for doc in values] for key, values in matches.items()}
        )
        self.fake_store = SimpleNamespace(documents=documents, document_calls=[])

    def search(self, query, *, limit):
        return [
            _hit(self.fake_store.documents[document_id])
            for document_id in self.fake_index.search(query, limit=limit)
            if document_id in self.fake_store.documents
        ]

    def get_document(self, document_id):
        self.fake_store.document_calls.append(document_id)
        return self.fake_store.documents.get(document_id)


def _browser(matches, documents):
    return _Browser(matches, documents)


def _settings():
    return SimpleNamespace(
        QUERY_CHUNK_MAX_TOKENS=220,
        QUERY_CHUNK_OVERLAP_TOKENS=24,
        FINAL_EVIDENCE_LIMIT=3,
        LLM_CONTEXT_MAX_TOKENS=720,
    )


def test_rescues_only_topical_verified_corpus_chunks_and_marks_provenance():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    content = (
        "Điều 1. Phạm vi điều chỉnh.\n"
        "1. Luật này quy định về hợp đồng lao động và tổ chức doanh nghiệp.\n"
        "Điều 2. Mức hưởng trợ cấp thất nghiệp.\n"
        "1. Người lao động đủ điều kiện được hưởng trợ cấp thất nghiệp theo mức quy định."
    )
    document = _document(17, "15/2022/QH15", "Luật về trợ cấp thất nghiệp", content)
    browser = _browser(
        {"15/2022/QH15": [document]},
        {17: document},
    )
    record = SimpleNamespace(
        document_number="15 / 2022 / QH15",
        title="Luật về trợ cấp thất nghiệp",
        issued_date="2022-01-01",
    )

    result = rescue_official_discoveries(
        query="mức hưởng trợ cấp thất nghiệp",
        records=[record],
        browser=browser,
        settings=_settings(),
    )

    assert browser.fake_index.search_calls == [("15/2022/QH15", 50)]
    assert browser.fake_store.document_calls == [17]
    assert result.evidence
    assert any("trợ cấp thất nghiệp" in chunk.text.casefold() for chunk in result.evidence)
    assert all(chunk.source_content_sha256 == document.content_sha256 for chunk in result.evidence)
    assert sum(chunk.token_count for chunk in result.evidence) <= 720
    assert len(result.evidence) <= 3
    assert result.diagnostics["corpus_documents_loaded"] == 1
    assert result.diagnostics["provenance"] == "pinned_corpus_store"
    assert result.diagnostics["official_discovery_used_as"] == "metadata_only"
    assert result.diagnostics["official_external_source_read"] is False
    assert result.diagnostics["legal_effect_asserted"] is False
    assert "query" not in result.diagnostics


def test_skips_corpus_text_when_recomputed_hash_does_not_match_store_hash():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    document = _document(
        18,
        "16/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 1. Trợ cấp thất nghiệp được quy định tại điều này.",
        digest="0" * 64,
    )
    browser = _browser({"16/2022/QH15": [document]}, {18: document})

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        [SimpleNamespace(document_number="16/2022/QH15")],
        browser,
        settings=_settings(),
    )

    assert result.evidence == ()
    assert result.diagnostics["candidates"][0]["status"] == "corpus_hash_mismatch"


def test_disambiguates_exact_number_collision_with_title_corroboration():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    wanted = _document(
        21,
        "17/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 1. Trợ cấp thất nghiệp được tính theo mức hưởng.",
    )
    collision = _document(
        22,
        "17/2022/QH15",
        "Luật về bảo hiểm xã hội",
        "Điều 1. Bảo hiểm xã hội được quy định tại luật này.",
    )
    browser = _browser(
        {"17/2022/QH15": [wanted, collision]},
        {21: wanted, 22: collision},
    )

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp mức hưởng",
        [SimpleNamespace(document_number="17/2022/QH15", title="Luật về trợ cấp thất nghiệp")],
        browser,
        settings=_settings(),
    )

    assert browser.fake_store.document_calls == [21]
    assert {chunk.document_id for chunk in result.evidence} == {21}
    assert result.diagnostics["candidates"][0]["match_resolution"] == "collision_corroborated"


def test_skips_ambiguous_number_collision_without_corroborating_metadata():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    first = _document(31, "18/2022/QH15", "Luật A", "Điều 1. Trợ cấp thất nghiệp.")
    second = _document(32, "18/2022/QH15", "Luật B", "Điều 1. Trợ cấp thất nghiệp.")
    browser = _browser(
        {"18/2022/QH15": [first, second]},
        {31: first, 32: second},
    )

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        [SimpleNamespace(document_number="18/2022/QH15")],
        browser,
        settings=_settings(),
    )

    assert browser.fake_store.document_calls == []
    assert result.evidence == ()
    assert result.diagnostics["candidates"][0]["status"] == "collision_ambiguous"


def test_loads_no_more_than_two_complete_corpus_documents():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    records = []
    matches = {}
    documents = {}
    for index in range(4):
        number = f"{index + 1}/2022/QH15"
        document = _document(
            40 + index,
            number,
            f"Luật {index}",
            "Điều 1. Người lao động được hưởng trợ cấp thất nghiệp.",
        )
        records.append(SimpleNamespace(document_number=number, title=document.metadata.title))
        matches[number] = [document]
        documents[document.metadata.document_id] = document
    browser = _browser(matches, documents)

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        records,
        browser,
        settings=_settings(),
    )

    assert len(browser.fake_store.document_calls) <= 2
    assert result.diagnostics["corpus_documents_loaded"] <= 2
    assert len({chunk.document_id for chunk in result.evidence}) <= 2


def test_rejects_search_results_without_the_exact_discovered_number():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    wrong_document = _document(
        50,
        "99/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 1. Trợ cấp thất nghiệp.",
    )
    browser = _browser({"19/2022/QH15": [wrong_document]}, {50: wrong_document})

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        [SimpleNamespace(document_number="19/2022/QH15")],
        browser,
        settings=_settings(),
    )

    assert result.evidence == ()
    assert browser.fake_store.document_calls == []
    assert result.diagnostics["candidates"][0]["status"] == "corpus_number_not_found"


def test_rejects_a_stored_record_whose_document_id_changed():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    search_hit = _document(
        53,
        "22/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 1. Trợ cấp thất nghiệp.",
    )
    wrong_stored_document = _document(
        54,
        "22/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 1. Trợ cấp thất nghiệp.",
    )
    browser = _browser({"22/2022/QH15": [search_hit]}, {53: wrong_stored_document})

    def return_stale_hit(_query, *, limit):
        return [_hit(search_hit)]

    browser.search = return_stale_hit

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        [SimpleNamespace(document_number="22/2022/QH15")],
        browser,
        settings=_settings(),
    )

    assert browser.fake_store.document_calls == [53]
    assert result.evidence == ()
    assert result.diagnostics["candidates"][0]["status"] == "corpus_document_id_changed"


def test_requires_topical_terms_and_uses_220_token_chunks_with_24_overlap():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    repeated_topic = " ".join(["trợ cấp thất nghiệp"] * 180)
    document = _document(
        51,
        "20/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        f"Điều 1. {repeated_topic}",
    )
    browser = _browser({"20/2022/QH15": [document]}, {51: document})
    records = [SimpleNamespace(document_number="20/2022/QH15")]

    result = rescue_official_discoveries(
        "trợ cấp thất nghiệp",
        records,
        browser,
        settings=SimpleNamespace(
            QUERY_CHUNK_MAX_TOKENS=500,
            QUERY_CHUNK_OVERLAP_TOKENS=0,
            FINAL_EVIDENCE_LIMIT=3,
            LLM_CONTEXT_MAX_TOKENS=720,
        ),
    )

    assert len(result.evidence) == 3
    assert all(len(chunk.text.split()) <= 220 for chunk in result.evidence)
    assert result.evidence[0].text.split()[-24:] == result.evidence[1].text.split()[:24]
    assert sum(len(chunk.text.split()) for chunk in result.evidence) <= 720


def test_generic_legal_references_and_amounts_do_not_count_as_topical_overlap():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    document = _document(
        52,
        "21/2022/QH15",
        "Luật về trợ cấp thất nghiệp",
        "Điều 5. Khoản 2. Mức hưởng là 10.000 đồng mỗi tháng.",
    )
    browser = _browser({"21/2022/QH15": [document]}, {52: document})

    for query in ("Điều 5 khoản 2", "mức 10.000 đồng mỗi tháng"):
        result = rescue_official_discoveries(
            query,
            [SimpleNamespace(document_number="21/2022/QH15")],
            browser,
            settings=_settings(),
        )

        assert result.evidence == ()
        assert result.diagnostics["candidates"][0]["status"] == "no_positive_topical_chunks"


def test_selects_meaningful_topic_phrases_and_skips_generic_overlap():
    from app.services.official_discovered_corpus_rescue import rescue_official_discoveries

    content = (
        "Điều 1. Quy định về phế liệu.\n"
        "1. Cơ sở tái chế phế liệu phải đáp ứng yêu cầu môi trường.\n"
        "2. Cơ sở xử lý chất thải phải có giấy phép môi trường.\n"
        "Điều 12. Xuất khẩu sản phẩm động vật.\n"
        "1. Việc xuất khẩu động vật phải có giấy phép kiểm dịch thú y."
    )
    document = _document(60, "23/2025/QH15", "Luật sửa đổi nhiều luật", content)
    browser = _browser({"23/2025/QH15": [document]}, {60: document})

    result = rescue_official_discoveries(
        "điều kiện xuất khẩu phế liệu và giấy phép môi trường",
        [SimpleNamespace(document_number="23/2025/QH15")],
        browser,
        settings=_settings(),
    )

    assert len(result.evidence) == 2
    assert all("Điều 1" in chunk.citation for chunk in result.evidence)
    assert all("Điều 12" not in chunk.citation for chunk in result.evidence)
