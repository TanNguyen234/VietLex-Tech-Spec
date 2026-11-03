from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest


def test_query_plan_uses_the_question_topic_instead_of_only_trailing_words():
    from app.services.free_web_research import build_free_web_queries

    question = (
        "Doanh nghiệp được khấu trừ tiền lương người lao động trong trường hợp "
        "thiếu hụt tài sản theo Bộ luật Lao động 2019 như thế nào?"
    )
    queries = build_free_web_queries(question)

    assert 1 <= len(queries) <= 5
    assert len(queries) == len(set(queries))
    assert all("khấu trừ" in query.casefold() and "lương" in query.casefold() for query in queries)
    assert all(2 <= len(query.split()) <= 8 for query in queries)


def test_queries_are_short_and_omit_personal_name_amount_and_as_of_date():
    from app.services.free_web_research import build_free_web_queries

    question = (
        "Nguyễn Văn An hỏi công ty có được khấu trừ tiền lương 85 triệu đồng "
        "tại ngày 17/10/2026 vì thiếu hụt tài sản không?"
    )
    queries = build_free_web_queries(question)

    assert queries
    assert all(2 <= len(query.split()) <= 8 for query in queries)
    assert all("nguyễn" not in query.casefold() for query in queries)
    assert all("85" not in query and "17/10/2026" not in query for query in queries)
    assert all("khấu trừ" in query.casefold() and "tiền lương" in query.casefold() for query in queries)


def test_topic_query_shapes_preserve_separate_legal_topics():
    from app.services.free_web_research import build_free_web_queries

    cases = [
        ("Điều kiện thử việc và tiền lương người lao động", ("thử việc", "lương")),
        ("Quyền sử dụng đất khi chuyển nhượng", ("đất",)),
        ("Nhập phế liệu, giấy phép môi trường", ("phế liệu", "giấy phép môi trường")),
        ("Chi phí thiết kế máy bay trong hàng không tại ngày 01/01/2026", ("chi phí", "thiết kế", "máy bay")),
    ]
    for question, expected in cases:
        queries = build_free_web_queries(question)
        joined = " ".join(queries).casefold()
        assert queries and len(queries) == len(set(queries))
        assert all(2 <= len(query.split()) <= 8 for query in queries)
        assert all(term in joined for term in expected)
    aviation = " ".join(build_free_web_queries(cases[-1][0])).casefold()
    assert "01/01/2026" not in aviation


@pytest.mark.asyncio
async def test_discovery_is_bounded_to_two_concurrent_queries_and_five_deduplicated_queries():
    from app.services.free_web_research import stream_free_web_research

    active = 0
    maximum = 0
    observed_queries = []

    class Provider:
        async def search(self, query, *, limit=3):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            observed_queries.append(query)
            await asyncio.sleep(0)
            active -= 1
            return SimpleNamespace(results=(), provider="test", method="test", errors=())

    events = [
        event
        async for event in stream_free_web_research(
            "Quy định về khấu trừ tiền lương người lao động", provider=Provider()
        )
    ]

    assert maximum <= 2
    assert len(observed_queries) <= 5
    assert len(observed_queries) == len(set(observed_queries))
    assert [event["type"] for event in events if event["type"] in {"query", "terminal"}]
    assert events[-1]["type"] == "terminal"


@pytest.mark.asyncio
async def test_filters_unapproved_urls_before_reading_and_keeps_only_three_readable_snapshots():
    from app.services.free_web_research import stream_free_web_research

    urls = [
        "https://evil.example/law",
        "https://vanban.chinhphu.vn/?docid=1",
        "https://congbao.chinhphu.vn/van-ban/law-2.htm",
        "https://baochinhphu.vn/law/3.htm",
        "https://vanban.chinhphu.vn/?docid=4",
        "https://vanban.chinhphu.vn/?docid=5",
    ]
    read_urls = []

    class Provider:
        async def search(self, query, *, limit=3):
            return SimpleNamespace(
                results=tuple(
                    SimpleNamespace(
                        url=url,
                        title=(f"Giấy phép môi trường phế liệu Official {index}" if index else "Official 0"),
                        domain=url.split("/")[2],
                        snippet="metadata snippet",
                        document_number="",
                        issued_date="",
                    )
                    for index, url in enumerate(urls)
                ),
                provider="test",
                method="test",
                errors=(),
            )

    async def reader(url, **kwargs):
        read_urls.append(url)
        if url.endswith("docid=1"):
            return {"url": url, "text": "", "content_status": "metadata_only"}
        if url.endswith("docid=2"):
            body = "Readable source body"
            digest = hashlib.sha256(body.encode()).hexdigest()
            return {
                "url": url,
                "title": "Readable official source",
                "text": body,
                "sha256": digest,
                "document_sha256": "d" * 64,
                "page_start": 1,
                "page_end": 1,
                "pages": [{"page": 1, "text": body}],
                "retrieved_at": "2026-10-17T00:00:00+00:00",
                "method": "visible_html_text",
            }
        return {
            "url": url,
            "title": "Readable official source",
            "text": "Readable source body",
            "sha256": hashlib.sha256(b"Readable source body").hexdigest(),
            "document_sha256": "e" * 64,
            "page_start": 1,
            "page_end": 1,
            "pages": [{"page": 1, "text": "Readable source body"}],
            "retrieved_at": "2026-10-17T00:00:00+00:00",
            "method": "visible_html_text",
        }

    events = [
        event
        async for event in stream_free_web_research(
            "Giấy phép môi trường đối với phế liệu", provider=Provider(), reader=reader
        )
    ]
    snapshots = [event["source"] for event in events if event["type"] == "source" and event.get("status") == "readable"]

    assert "https://evil.example/law" not in read_urls
    assert len(read_urls) == 3
    assert len(snapshots) <= 3
    assert len(snapshots) == 2
    assert all("https://" in snapshot["url"] for snapshot in snapshots)
    assert all(snapshot["snapshot_key"] for snapshot in snapshots)
    assert all(snapshot["snapshot_timestamp"] for snapshot in snapshots)
    assert all("metadata snippet" not in snapshot.get("text", "") for snapshot in snapshots)


@pytest.mark.asyncio
async def test_reader_url_mismatch_and_empty_or_metadata_only_results_are_not_sources():
    from app.services.free_web_research import stream_free_web_research

    urls = [
        "https://vanban.chinhphu.vn/?docid=1",
        "https://vanban.chinhphu.vn/?docid=2",
        "https://vanban.chinhphu.vn/?docid=3",
    ]

    class Provider:
        async def search(self, query, *, limit=3):
            return SimpleNamespace(
                results=tuple(
                    SimpleNamespace(url=url, title="Source", domain="vanban.chinhphu.vn", snippet="snippet")
                    for url in urls
                ), provider="test", method="test", errors=()
            )

    async def reader(url, **kwargs):
        if url.endswith("docid=1"):
            return {"url": url, "text": "", "content_status": "metadata_only"}
        if url.endswith("docid=2"):
            return {"url": "https://vanban.chinhphu.vn/?docid=elsewhere", "text": "wrong URL"}
        return {"url": url, "text": "   "}

    events = [
        event
        async for event in stream_free_web_research(
            "Quy định lao động", provider=Provider(), reader=reader
        )
    ]

    assert not [event for event in events if event["type"] == "source" and event.get("status") == "readable"]
    assert events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_provider_hardwall_is_capped_at_ten_seconds_and_query_error_is_visible(monkeypatch):
    from app.services.free_web_research import stream_free_web_research

    class Provider:
        async def search(self, query, *, limit=3):
            await asyncio.sleep(0.05)
            return SimpleNamespace(results=(), provider="test", method="test", errors=())

    events = [
        event
        async for event in stream_free_web_research(
            "Quy định lao động",
            provider=Provider(),
            settings=SimpleNamespace(
                FREE_WEB_RESEARCH_PROVIDER_TIMEOUT_SECONDS=10,
                FREE_WEB_RESEARCH_DISCOVERY_BUDGET_SECONDS=0.01,
                FREE_WEB_RESEARCH_READ_BUDGET_SECONDS=0.02,
                FREE_WEB_RESEARCH_TOTAL_BUDGET_SECONDS=0.1,
                FREE_WEB_RESEARCH_NETWORK_CONCURRENCY=2,
            ),
        )
    ]

    assert events[-1]["type"] == "terminal"
    assert events[-1]["status"] in {"partial", "failed"}
    assert any(event["type"] == "query" and event.get("error_kind") for event in events)


@pytest.mark.asyncio
async def test_reader_discovery_never_enables_ocr_and_uses_smart_bounded_pages():
    from app.services.free_web_research import stream_free_web_research

    seen = []

    class Provider:
        async def search(self, query, *, limit=3):
            return SimpleNamespace(
                results=(SimpleNamespace(
                    url="https://vanban.chinhphu.vn/?docid=1", title="Luật lao động",
                    domain="vanban.chinhphu.vn", snippet="metadata only",
                ),), provider="test", method="test", errors=()
            )

    async def reader(url, **kwargs):
        seen.append(kwargs)
        text = "full body"
        return {"url": url, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "retrieved_at": "now"}

    events = [event async for event in stream_free_web_research("Luật lao động", provider=Provider(), reader=reader)]

    assert len([event for event in events if event["type"] == "source" and event.get("status") == "readable"]) == 1
    assert seen == [{"question": "Luật lao động", "smart_pages": True, "use_ocr": False, "page_limit": 5}]


def _saved_pdf_snapshot(*, question="điều kiện khấu trừ tiền lương", page_start=3, version="pdf-v1"):
    from app.services.free_web_research import _snapshot

    url = "https://vanban.chinhphu.vn/?docid=cache-test"
    pages = [
        {"page": page_start, "text": "Page one body"},
        {"page": page_start + 1, "text": "Page two body"},
    ]
    text = "\n\n".join(page["text"] for page in pages)
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = {
        "url": url,
        "title": "Official document",
        "text": text,
        "sha256": digest,
        "text_sha256": digest,
        "document_sha256": "d" * 64,
        "page_start": page_start,
        "page_end": page_start + 1,
        "page_count": 20,
        "pages": pages,
        "method": "pdf_text",
        "extraction_version": version,
        "content_status": "readable",
        "inspected_pages": [1, 5, page_start, page_start + 1],
    }
    return _snapshot(
        source,
        url,
        workspace_id="workspace-1",
        owner_scope="user:1",
        question=question,
    )


def test_pdf_snapshot_accepts_page_whitespace_normalized_in_joined_text():
    from app.services.free_web_research import _valid_snapshot_content

    pages = [
        {"page": 3, "text": "  Điều 1.\tNội dung   "},
        {"page": 4, "text": "\nĐiều 2. Kết quả  "},
    ]
    text = "Điều 1. Nội dung Điều 2. Kết quả"
    source = {
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "pages": pages,
        "page_start": 3,
        "page_end": 4,
    }

    assert _valid_snapshot_content(source) is True

    tampered = {**source, "text": "Điều 1. Khác Điều 2. Kết quả"}
    tampered["sha256"] = hashlib.sha256(tampered["text"].encode()).hexdigest()
    assert _valid_snapshot_content(tampered) is False


def test_pdf_snapshot_cache_is_owner_workspace_url_hash_page_and_version_scoped():
    from app.services.free_web_research import _cached_snapshot

    question = "điều kiện khấu trừ tiền lương"
    snapshot = _saved_pdf_snapshot(question=question)
    now = datetime.fromisoformat(snapshot["snapshot_timestamp"])
    assert _cached_snapshot(
        [snapshot], snapshot["url"], question=question, workspace_id="workspace-1",
        owner_scope="user:1", now=now,
    )["snapshot_reused"] is True

    for candidate, url, workspace, owner in (
        (snapshot, snapshot["url"], "workspace-2", "user:1"),
        (snapshot, snapshot["url"], "workspace-1", "user:2"),
        (snapshot, "https://vanban.chinhphu.vn/?docid=other", "workspace-1", "user:1"),
        ({**snapshot, "page_start": 4}, snapshot["url"], "workspace-1", "user:1"),
        ({**snapshot, "extraction_version": "pdf-v2"}, snapshot["url"], "workspace-1", "user:1"),
        ({**snapshot, "document_sha256": "e" * 64}, snapshot["url"], "workspace-1", "user:1"),
        ({**snapshot, "text": "tampered"}, snapshot["url"], "workspace-1", "user:1"),
    ):
        assert _cached_snapshot(
            [candidate], url, question=question, workspace_id=workspace,
            owner_scope=owner, now=now,
        ) is None
    assert _cached_snapshot(
        [snapshot], snapshot["url"], question=question, workspace_id="workspace-1",
        owner_scope="user:1", now=now + timedelta(minutes=16),
    ) is None


def test_pdf_cache_requires_same_query_and_current_law_always_refreshes():
    from app.services.free_web_research import _cached_snapshot

    question = "điều kiện khấu trừ tiền lương"
    snapshot = _saved_pdf_snapshot(question=question)
    now = datetime.fromisoformat(snapshot["snapshot_timestamp"])
    assert _cached_snapshot(
        [snapshot], snapshot["url"], question="hiện hành khấu trừ tiền lương",
        workspace_id="workspace-1", owner_scope="user:1", now=now,
    ) is None
    assert _cached_snapshot(
        [snapshot], snapshot["url"], question="thiếu hụt tài sản và tiền lương",
        workspace_id="workspace-1", owner_scope="user:1", now=now,
    ) is None


@pytest.mark.asyncio
async def test_html_cache_reuses_same_official_body_but_refresh_and_current_law_fetch_again():
    from app.services.free_web_research import stream_free_web_research

    url = "https://vanban.chinhphu.vn/?docid=html-cache"
    calls = []

    class Provider:
        async def search(self, query, *, limit=3):
            return SimpleNamespace(
                results=(SimpleNamespace(
                    url=url, title="Khấu trừ tiền lương theo Bộ luật Lao động", domain="vanban.chinhphu.vn", snippet="metadata"
                ),), provider="test", method="test", errors=()
            )

    async def reader(read_url, **_kwargs):
        calls.append(read_url)
        body = "Official HTML legal body"
        return {
            "url": read_url,
            "text": body,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "retrieved_at": "2026-10-17T00:00:00+00:00",
            "method": "visible_html_text",
        }

    first = [event async for event in stream_free_web_research(
        "khấu trừ tiền lương", provider=Provider(), reader=reader,
        workspace_id="workspace-1", owner_scope="user:1",
    )]
    cached = next(event["source"] for event in first if event["type"] == "source" and event.get("status") == "readable")
    second = [event async for event in stream_free_web_research(
        "khấu trừ tiền lương", provider=Provider(), reader=reader,
        workspace_id="workspace-1", owner_scope="user:1", cached_sources=[cached],
    )]
    assert calls == [url]
    assert next(event["source"] for event in second if event["type"] == "source")["snapshot_reused"] is True
    assert next(event for event in second if event["type"] == "terminal")["fetched_count"] == 0

    refreshed = [event async for event in stream_free_web_research(
        "khấu trừ tiền lương", provider=Provider(), reader=reader,
        workspace_id="workspace-1", owner_scope="user:1", cached_sources=[cached], refresh=True,
    )]
    current_law = [event async for event in stream_free_web_research(
        "hiện hành khấu trừ tiền lương", provider=Provider(), reader=reader,
        workspace_id="workspace-1", owner_scope="user:1", cached_sources=[cached],
    )]
    assert calls == [url, url, url]
    assert next(event for event in refreshed if event["type"] == "terminal")["fetched_count"] == 1
    assert next(event for event in current_law if event["type"] == "terminal")["fetched_count"] == 1


def _captured_candidate(url, title, snippet):
    return SimpleNamespace(
        url=url,
        title=title,
        domain="congbao.chinhphu.vn",
        snippet=snippet,
        document_number="",
        issued_date="",
    )


@pytest.mark.asyncio
async def test_unrelated_salary_titles_are_not_read_for_probation_question():
    from app.services.free_web_research import build_free_web_queries, stream_free_web_research

    question = "Tôi mới nhận việc, công ty đề nghị hai tháng thử việc chỉ trả 70% lương. Tôi cần kiểm tra quy định gì?"
    rows = (
        _captured_candidate(
            "https://congbao.chinhphu.vn/van-ban/thong-tu-lien-tich-so-31-2014-ttlt-bldtbxh-bqp-6131.htm",
            "Thông tư liên tịch số 31/2014 sửa đổi hướng dẫn thí điểm quản lý tiền lương đối với Tập đoàn Viễn thông Quân đội",
            "Hướng dẫn thực hiện thí điểm quản lý tiền lương đối với Công ty mẹ - Tập đoàn Viễn thông Quân đội giai đoạn 2011 - 2013.",
        ),
        _captured_candidate(
            "https://congbao.chinhphu.vn/van-ban/thong-tu-so-05-2024-tt-bnv-42249.htm",
            "Thông tư số 05/2024/TT-BNV quy định tiêu chuẩn xét thăng hạng viên chức; xếp lương đối với người được tuyển dụng vào viên chức.",
            "Trường hợp đã xếp lương theo các bảng lương của nhà nước và chuyển công tác thì thực hiện xếp lương tương ứng.",
        ),
        _captured_candidate(
            "https://congbao.chinhphu.vn/van-ban/thong-tu-so-07-2017-tt-bnv-24942.htm",
            "Thông tư số 07/2017/TT-BNV hướng dẫn chế độ tiền lương đối với người làm việc trong tổ chức cơ yếu.",
            "Nâng bậc lương trước thời hạn đối với người làm công tác cơ yếu.",
        ),
    )
    observed_queries = []
    read_urls = []

    class Provider:
        async def search(self, query, *, limit=3):
            observed_queries.append(query)
            return SimpleNamespace(results=rows, provider="captured-fixture", method="fixture", errors=())

    async def reader(url, **_kwargs):
        read_urls.append(url)
        text = "captured reader fixture body"
        return {"url": url, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "retrieved_at": "2026-10-17T00:00:00+00:00"}

    events = [event async for event in stream_free_web_research(question, provider=Provider(), reader=reader)]
    queries = build_free_web_queries(question)

    assert len(queries) <= 5
    assert any("Bộ luật Lao động" in query for query in queries)
    assert observed_queries == queries
    assert read_urls == []
    assert events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_environment_title_and_snippet_rank_over_unrelated_energy_laws():
    from app.services.free_web_research import build_free_web_queries, stream_free_web_research

    question = "Xưởng nhập phế liệu từ nước ngoài làm nguyên liệu có cần giấy phép môi trường không?"
    target_url = "https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-08-2022-nd-cp-36666.htm"
    rows = (
        _captured_candidate(
            "https://congbao.chinhphu.vn/van-ban/luat-so-50-2010-qh12-2959.htm",
            "Luật số 50/2010/QH12 luật Sử dụng năng lượng tiết kiệm và hiệu quả.",
            "Luật Sử dụng năng lượng tiết kiệm và hiệu quả. Đầu tư hiện đại hóa dây chuyền sản xuất.",
        ),
        _captured_candidate(
            "https://congbao.chinhphu.vn/van-ban/luat-so-77-2025-qh15-45576.htm",
            "Luật số 77/2025/QH15 sửa đổi, bổ sung Luật Sử dụng năng lượng tiết kiệm và hiệu quả.",
            "Luật sửa đổi, bổ sung một số điều của Luật Sử dụng năng lượng tiết kiệm và hiệu quả.",
        ),
        _captured_candidate(
            target_url,
            "Nghị định số 08/2022/NĐ-CP quy định chi tiết một số điều của Luật Bảo vệ môi trường.",
            "Giấy phép môi trường thành phần trong nhập khẩu phế liệu làm nguyên liệu sản xuất được kéo dài đến hết ngày 31 tháng 12 năm 2022.",
        ),
    )
    read_urls = []

    class Provider:
        async def search(self, query, *, limit=3):
            return SimpleNamespace(results=rows, provider="captured-fixture", method="fixture", errors=())

    async def reader(url, **_kwargs):
        read_urls.append(url)
        text = "captured reader fixture body"
        return {"url": url, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "retrieved_at": "2026-10-17T00:00:00+00:00"}

    events = [event async for event in stream_free_web_research(question, provider=Provider(), reader=reader)]
    queries = build_free_web_queries(question)

    assert len(queries) <= 5
    assert any("Luật Bảo vệ môi trường" in query for query in queries)
    assert read_urls == [target_url]
    assert [event["source"]["url"] for event in events if event["type"] == "source" and event.get("status") == "readable"] == [target_url]
def test_queries_do_not_search_negated_privacy_scope_instead_of_deposit():
    from app.services.free_web_research import build_free_web_queries
    queries = build_free_web_queries('QA tra cứu Bộ luật Dân sự2015 về đặt cọc; không dữ liệu cá nhân')
    assert queries
    assert all('dữ liệu' not in query.casefold() and 'cá nhân' not in query.casefold() for query in queries)
    assert any('Bộ luật Dân sự' in query for query in queries)


def test_queries_preserve_words_adjacent_to_amount_or_statutory_year():
    from app.services.free_web_research import build_free_web_queries
    queries = build_free_web_queries('Bộ luật Lao động2019 thử việc cao đẳng60 ngày tiền lương85 phần trăm')
    assert any('tiền lương' in query.casefold() for query in queries)


def test_queries_keep_explicit_law_year_in_narrow_title_search():
    from app.services.free_web_research import build_free_web_queries
    queries = build_free_web_queries('Theo Bộ luật Lao động2019, thời gian thử việc tối đa?')
    assert any('Bộ luật Lao động 2019' in query for query in queries)


