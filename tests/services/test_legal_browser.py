from types import SimpleNamespace

import httpx


class _Index:
    def __init__(self, ids):
        self.ids = ids
        self.calls = []

    def search(self, query: str, *, limit: int):
        self.calls.append((query, limit))
        return self.ids[:limit]


class _Store:
    def __init__(self):
        self.metadata = {
            7: SimpleNamespace(
                document_id=7,
                document_number="45/2019/QH14",
                title="Bộ luật Lao động 2019",
                source_url="https://example.gov.vn/7",
                legal_type="Bộ luật",
                legal_sectors="Lao động",
                issuing_authority="Quốc hội",
                issuance_date="2019-11-20",
            )
        }
        self.documents = {
            7: SimpleNamespace(metadata=self.metadata[7], content="Điều 25...", quality_flags=())
        }

    def get_metadata_many(self, ids):
        return {value: self.metadata[value] for value in ids if value in self.metadata}

    def get_many(self, ids):
        return {value: self.documents[value] for value in ids if value in self.documents}


def test_legal_browser_reuses_title_number_index_and_caps_results() -> None:
    from app.services.legal_browser import LegalBrowser

    index = _Index([7, 8, 9])
    browser = LegalBrowser(store=_Store(), index=index)

    results = browser.search("45/2019/QH14", limit=2)

    assert index.calls == [("45/2019/QH14", 2)]
    assert [result.document_id for result in results] == [7]
    assert results[0].title == "Bộ luật Lao động 2019"


def test_legal_browser_blank_query_and_missing_document_are_empty() -> None:
    from app.services.legal_browser import LegalBrowser

    browser = LegalBrowser(store=_Store(), index=_Index([7]))

    assert browser.search("   ", limit=20) == []
    assert browser.get_document(999) is None
    assert browser.get_document(7).content == "Điều 25..."


def test_supabase_filters_are_applied_before_limit():
    from app.services.legal_browser import SupabaseLegalStore, SearchFilters
    requests = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=[])))
    store = SupabaseLegalStore(url="https://project.supabase.co", publishable_key="test", client=client)
    store.search("lao động", limit=20, filters=SearchFilters(legal_type="Bộ luật", authority="Quốc hội", issued_from="2019-01-01", issued_to="2020-01-01", sort="newest"))
    params = requests[0].url.params
    assert params["legal_type"] == "eq.Bộ luật"
    assert params["issuing_authority"] == "eq.Quốc hội"
    assert params["and"] == "(issuance_date.gte.2019-01-01,issuance_date.lte.2020-01-01)"
    assert params["order"] == "issuance_date.desc.nullslast,document_id.asc"
    assert params["limit"] == "20"


def test_corpus_quality_queue_reads_bounded_metadata_without_full_content():
    from app.services.legal_browser import SupabaseLegalStore, LegalBrowser
    requests = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=[])))
    store = SupabaseLegalStore(url="https://project.supabase.co", publishable_key="test", client=client)
    assert LegalBrowser(store=store, index=store).quality_queue("missing_date", offset=50) == []
    params = requests[0].url.params
    assert params["issuance_date"] == "is.null"
    assert params["limit"] == "50" and params["offset"] == "50"
    assert "content" not in params["select"]


def test_local_filters_are_not_applied_to_an_already_truncated_page(tmp_path):
    import sqlite3
    from app.services.legal_browser import LegalBrowser, SearchFilters
    store = _Store()
    store.path = tmp_path / "content.sqlite3"
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TABLE metadata(document_id INTEGER, document_number TEXT, title TEXT, legal_type TEXT, issuing_authority TEXT, issuance_date TEXT)")
        connection.executemany("INSERT INTO metadata VALUES(?,?,?,?,?,?)", [(i, "X", "lao động", "Khác", "", "2020-01-01") for i in range(6)])
        connection.execute("INSERT INTO metadata VALUES(7,'45/2019/QH14','lao động','Bộ luật','Quốc hội','2019-11-20')")
    result = LegalBrowser(store=store, index=_Index([])).search("lao động", limit=1, filters=SearchFilters(legal_type="Bộ luật"))
    assert [row.document_id for row in result] == [7]


def test_supabase_legal_store_reads_search_and_full_document() -> None:
    from app.services.legal_browser import SupabaseLegalStore

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        select = request.url.params.get("select", "")
        if select == "document_id":
            return httpx.Response(200, json=[{"document_id": 7}])
        return httpx.Response(
            200,
            json=[
                {
                    "document_id": 7,
                    "document_number": "45/2019/QH14",
                    "title": "Bộ luật Lao động 2019",
                    "source_url": "https://example.gov.vn/7",
                    "legal_type": "Bộ luật",
                    "legal_sectors": "Lao động",
                    "issuing_authority": "Quốc hội",
                    "issuance_date": "2019-11-20",
                    "content": "Điều 25...",
                    "content_sha256": "abc",
                    "content_store_key": "content/7",
                    "quality_flags": [],
                }
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = SupabaseLegalStore(
        url="https://project.supabase.co",
        publishable_key="publishable-test",
        client=client,
    )

    assert store.search("45/2019/QH14", limit=20) == [7]
    document = store.get_many([7])[7]

    assert document.metadata.title == "Bộ luật Lao động 2019"
    assert document.content == "Điều 25..."
    assert requests[0].headers["apikey"] == "publishable-test"
    assert requests[0].url.params["limit"] == "20"


def test_supabase_legal_store_surfaces_http_failures() -> None:
    from app.services.legal_browser import (
        LegalBrowserBackendError,
        SupabaseLegalStore,
    )

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, request=request)
        )
    )
    store = SupabaseLegalStore(
        url="https://project.supabase.co",
        publishable_key="publishable-test",
        client=client,
    )

    try:
        store.search("lao động", limit=20)
    except LegalBrowserBackendError as error:
        assert error.status_code == 503
    else:
        raise AssertionError("Supabase HTTP failure must remain observable")
