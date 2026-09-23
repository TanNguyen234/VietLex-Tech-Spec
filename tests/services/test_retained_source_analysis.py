import pytest


def workspace():
    def row(id, digest, pages):
        return {
            "analysis_id": id,
            "kind": "trusted_sources",
            "result": {
                "sources": [
                    {
                        "url": "https://vanban.chinhphu.vn/?docid=1",
                        "document_sha256": digest,
                        "page_count": 3,
                        "pages": pages,
                        "method": "vertex_ocr",
                        "title": "Law",
                    }
                ]
            },
        }

    return {
        "analyses": [
            row(
                "first",
                "a" * 64,
                [{"page": 1, "text": "First"}, {"page": 2, "text": "Old"}],
            ),
            row("other", "b" * 64, [{"page": 3, "text": "Wrong version"}]),
            row("last", "a" * 64, [{"page": 2, "text": "New"}]),
        ]
    }


def test_collects_same_version_in_page_order_without_inventing_missing_text():
    from app.services.retained_source_analysis import collect_retained_source

    source = collect_retained_source(workspace(), "first", 0)
    assert [(p["page"], p["text"]) for p in source["pages"]] == [
        (1, "First"),
        (2, "New"),
    ]
    assert source["missing_pages"] == [3]
    assert source["readable_pages"] == [1, 2]
    assert source["pages"][1]["analysis_id"] == "last"
    assert "Wrong version" not in str(source)


def test_rejects_oversize_instead_of_silently_cutting():
    from app.services.retained_source_analysis import collect_retained_source

    data = workspace()
    data["analyses"][0]["result"]["sources"][0]["pages"][0]["text"] = "x" * 120001
    with pytest.raises(ValueError, match="source_scope_too_large"):
        collect_retained_source(data, "first", 0)


def test_no_source_or_hash_cannot_expand_scope():
    from app.services.retained_source_analysis import collect_retained_source

    with pytest.raises(ValueError):
        collect_retained_source(workspace(), "missing", 0)
    data = workspace()
    data["analyses"][0]["result"]["sources"][0]["document_sha256"] = ""
    with pytest.raises(ValueError):
        collect_retained_source(data, "first", 0)


def test_pdf_window_truncation_flag_does_not_discard_retained_pages():
    from app.services.retained_source_analysis import collect_retained_source

    data = workspace()
    for row in data["analyses"]:
        row["result"]["sources"][0]["truncated"] = True
    assert collect_retained_source(data, "first", 0)["readable_pages"] == [1, 2]


def test_model_selects_server_passages_without_retyping_legal_text():
    from app.services.retained_source_analysis import (
        collect_retained_source,
        validate_source_answer,
    )

    source = collect_retained_source(workspace(), "first", 0)
    raw = {
        "text": "New (trang 2)",
        "status": "ok",
        "unanswered_parts": [],
        "citations": ["p2-s0"],
    }
    result = validate_source_answer(raw, source)
    assert result["citations"][0]["quote"] == "New"
    assert result["citations"][0]["page"] == 2
    raw["citations"] = ["p999-s0"]
    with pytest.raises(ValueError):
        validate_source_answer(raw, source)


def test_passages_preserve_every_character_without_duplication():
    from app.services.retained_source_analysis import source_passages

    text = ("Điều khoản có dấu.\n" * 150) + "End"
    source = {
        "pages": [{"page": 1, "text": text, "analysis_id": "read", "source_index": 0}]
    }
    passages = list(source_passages(source).values())
    assert "".join(p["quote"] for p in passages) == text
    assert all(len(p["quote"]) <= 900 for p in passages)


@pytest.mark.asyncio
async def test_provider_receives_the_same_ids_accepted_by_validator(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.services import retained_source_analysis as service

    source = service.collect_retained_source(workspace(), "first", 0)

    async def generate(prompt, system):
        supplied = json.loads(prompt)["source"]["passages"]
        assert supplied[1]["passage_id"] == "p2-s0"
        return SimpleNamespace(
            status="success",
            text=json.dumps(
                {
                    "text": "New",
                    "status": "ok",
                    "citations": [supplied[1]["passage_id"]],
                    "unanswered_parts": [],
                }
            ),
            observed_provider="test",
            observed_model="test",
        )

    monkeypatch.setattr(service, "_generate", generate)
    result = await service.analyze_retained_source("Explain", source)
    assert result["citations"][0]["quote"] == "New"


def test_long_document_accepts_32_real_citations_without_dropping_them():
    from app.services.retained_source_analysis import (
        source_passages,
        validate_source_answer,
    )

    source = {
        "pages": [
            {"page": 1, "text": "a " * 16000, "analysis_id": "read", "source_index": 0}
        ]
    }
    ids = list(source_passages(source))[:32]
    result = validate_source_answer(
        {"text": "Summary", "status": "ok", "unanswered_parts": [], "citations": ids},
        source,
    )
    assert len(result["citations"]) == 32


def test_official_metadata_is_citable_but_not_presented_as_pdf_quote():
    from app.services.retained_source_analysis import (
        collect_retained_source,
        validate_source_answer,
        source_passages,
    )

    data = workspace()
    anchor = data["analyses"][0]["result"]["sources"][0]
    anchor.update(
        document_number="68/2026/TT-BXD",
        issued_date="10-09-2026",
        reported_effective_from="01-01-2027",
    )
    source = collect_retained_source(data, "first", 0)
    metadata = source_passages(source)["source-metadata"]
    assert metadata["citation_kind"] == "metadata"
    assert "10-09-2026" in metadata["quote"]
    result = validate_source_answer(
        {
            "text": "Date from portal",
            "status": "ok",
            "unanswered_parts": [],
            "citations": ["source-metadata"],
        },
        source,
    )
    assert result["citations"][0]["analysis_id"] == "first"


def test_relevant_passages_selects_cost_rules_and_date_with_bounded_context():
    from app.services.retained_source_analysis import relevant_source_passages
    source = {
        "pages": [{"page": 1, "text": ("Mục lục và thủ tục chung. " * 45), "analysis_id": "a", "source_index": 0},
                  {"page": 2, "text": ("Chi phí trực tiếp khi khai thác hạ tầng hàng không được xác định theo từng hoạt động. " * 12), "analysis_id": "a", "source_index": 0},
                  {"page": 3, "text": ("Chi phí gián tiếp dùng chung được phân bổ theo tiêu chí sử dụng tài sản. " * 12), "analysis_id": "a", "source_index": 0},
                  {"page": 4, "text": ("Quy định chuyển tiếp và trách nhiệm. " * 40), "analysis_id": "a", "source_index": 0}],
        "document_number": "68/2026/TT-BXD", "issued_date": "10-09-2026",
        "reported_effective_from": "01-01-2027", "origin_analysis_id": "a", "origin_source_index": 0,
    }
    question = 'Chi phí trực tiếp và gián tiếp được phân bổ thế nào tại ngày 13/09/2026?'
    selected = relevant_source_passages(question, source, limit=3)
    assert len(selected) == 3
    assert {row['page'] for row in selected.values()} == {0, 2, 3}
    assert 'source-metadata' in selected


def test_relevant_passages_preserves_relevant_article_continuation(monkeypatch):
    from app.services import retained_source_analysis as service
    passages = {
        'p1-s0': {'page': 1, 'quote': 'Tiêu đề chi phí gián tiếp và phân bổ.', 'analysis_id': 'a', 'source_index': 0},
        'p2-s0': {'page': 2, 'quote': '\nĐiều 5. Tiêu chí phân bổ chi phí gián tiếp\nChi phí dùng chung được phân bổ theo tỷ lệ doanh thu', 'analysis_id': 'a', 'source_index': 0},
        'p2-s900': {'page': 2, 'quote': 'từ việc cung cấp dịch vụ sử dụng tài sản kết cấu hạ tầng hàng không.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(passages))
    selected = service.relevant_source_passages('Chi phí gián tiếp phân bổ thế nào?', {}, limit=2)
    assert list(selected) == ['p2-s0', 'p2-s900']


def test_relevant_passages_keeps_article_continuation_across_page(monkeypatch):
    from app.services import retained_source_analysis as service
    rows = {
        'p1-s0': {'page': 1, 'quote': 'Điều 4. Chi phí trực tiếp\nCác khoản chi phí bao gồm', 'analysis_id': 'a', 'source_index': 0},
        'p2-s0': {'page': 2, 'quote': 'nhân công, nguyên vật liệu và dịch vụ mua ngoài.', 'analysis_id': 'a', 'source_index': 0},
        'p2-s900': {'page': 2, 'quote': 'Quy định kiểm tra chung.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(rows))
    assert list(service.relevant_source_passages('Chi phí trực tiếp bao gồm gì?', {}, limit=2)) == ['p1-s0', 'p2-s0']


def test_relevant_passages_keeps_conditions_after_numbered_article_heading(monkeypatch):
    from app.services import retained_source_analysis as service
    rows = {
        'p3-s843': {'page': 3, 'quote': 'Điều 5. Tiêu chí nhập khẩu dây chuyền công nghệ đã qua sử dụng.', 'analysis_id': 'a', 'source_index': 0},
        'p3-s1710': {'page': 3, 'quote': '2. Công suất tối thiểu; 3. Công nghệ không thuộc danh mục cấm.', 'analysis_id': 'a', 'source_index': 0},
        'p16-s0': {'page': 16, 'quote': 'Nhập khẩu dây chuyền công nghệ đã qua sử dụng tại ngày này.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(rows))
    selected = service.relevant_source_passages('Tiêu chí nhập khẩu dây chuyền công nghệ đã qua sử dụng?', {}, limit=2)
    assert list(selected) == ['p3-s843', 'p3-s1710']


def test_relevant_passages_ranks_specific_article_heading_before_generic_heading(monkeypatch):
    from app.services import retained_source_analysis as service
    rows = {
        'p1-s0': {'page': 1, 'quote': 'Điều 2. Nhập khẩu dây chuyền\nĐiều kiện công nghệ đã qua sử dụng được nhắc đến ở đây.', 'analysis_id': 'a', 'source_index': 0},
        'p2-s0': {'page': 2, 'quote': 'Điều 5. Điều kiện nhập khẩu dây chuyền công nghệ đã qua sử dụng.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(rows))
    selected = service.relevant_source_passages('Điều kiện nhập khẩu dây chuyền công nghệ đã qua sử dụng?', {}, limit=1)
    assert list(selected) == ['p2-s0']


def test_relevant_passages_does_not_extend_into_next_article(monkeypatch):
    from app.services import retained_source_analysis as service
    rows = {
        'p1-s0': {'page': 1, 'quote': 'Điều 5. Tiêu chí nhập khẩu dây chuyền công nghệ.', 'analysis_id': 'a', 'source_index': 0},
        'p1-s900': {'page': 1, 'quote': 'Điều 6. Chế độ báo cáo.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(rows))
    selected = service.relevant_source_passages('Tiêu chí nhập khẩu dây chuyền công nghệ?', {}, limit=2)
    assert list(selected) == ['p1-s0']


def test_relevant_passages_restore_original_reading_order_after_ranking(monkeypatch):
    from app.services import retained_source_analysis as service
    rows = {
        'p1-s0': {'page': 1, 'quote': 'Chi phí trực tiếp được xác định riêng.', 'analysis_id': 'a', 'source_index': 0},
        'p2-s0': {'page': 2, 'quote': 'Điều 5. Phân bổ chi phí gián tiếp theo tỷ lệ doanh thu.', 'analysis_id': 'a', 'source_index': 0},
    }
    monkeypatch.setattr(service, 'source_passages', lambda source: dict(rows))
    selected = service.relevant_source_passages('Phân bổ chi phí gián tiếp và trực tiếp?', {}, limit=2)
    assert list(selected) == ['p1-s0', 'p2-s0']


def test_temporal_context_separates_issuance_from_reported_effective_date():
    from app.services.retained_source_analysis import source_temporal_context
    source = {'issued_date': '10-09-2026', 'reported_effective_from': '01-01-2027'}
    result = source_temporal_context('Xét tại ngày 13/09/2026', source)
    assert result['as_of'] == '2026-09-13'
    assert result['status'] == 'issued_not_effective'
    assert source_temporal_context('Xét tại ngày 09/09/2026', source)['status'] == 'not_issued'
    assert source_temporal_context('Xét tại ngày 02/01/2027', source)['status'] == 'reported_effective_by_as_of'
    assert source_temporal_context('Xét tại ngày 13/09/2026', {})['status'] == 'unknown'


@pytest.mark.asyncio
async def test_relevant_answer_sends_only_selected_excerpts_and_temporal_context(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.services import retained_source_analysis as service
    source = {'pages': [
        {'page': 1, 'text': 'Unrelated administration.' * 50, 'analysis_id': 'a', 'source_index': 0},
        {'page': 2, 'text': 'Chi phí gián tiếp được phân bổ theo tiêu chí doanh thu.',
         'analysis_id': 'a', 'source_index': 0}],
        'issued_date': '10-09-2026', 'reported_effective_from': '01-01-2027',
        'origin_analysis_id': 'a', 'origin_source_index': 0}
    async def generate(prompt, system):
        payload = json.loads(prompt)['source']
        assert payload['temporal_context']['status'] == 'issued_not_effective'
        ids = [row['passage_id'] for row in payload['passages']]
        assert ids == ['source-metadata', 'p2-s0']
        return SimpleNamespace(status='success', text=json.dumps({
            'text': 'Chi phí gián tiếp được phân bổ theo tiêu chí doanh thu. [p2-s0]',
            'status': 'ok', 'citations': ['p2-s0'], 'unanswered_parts': []}),
            observed_provider='test', observed_model='test')
    monkeypatch.setattr(service, '_generate', generate)
    result = await service.analyze_retained_source(
        'Chi phí gián tiếp được phân bổ thế nào xét tại ngày 13/09/2026?',
        source, relevant_only=True)
    assert result['context_selection'] == {'method': 'lexical_relevance_v1', 'selected': 2, 'available': 4}
