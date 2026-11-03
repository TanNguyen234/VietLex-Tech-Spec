from types import SimpleNamespace

import httpx


def test_supabase_store_counts_full_documents_from_exact_head():
    from app.services.legal_browser import SupabaseLegalStore

    def respond(request):
        assert request.method == "HEAD"
        assert request.url.params["limit"] == "0"
        assert request.headers["prefer"] == "count=exact"
        return httpx.Response(206, headers={"content-range": "*/14962"})

    store = SupabaseLegalStore(
        url="https://project.supabase.co", publishable_key="test",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    assert store.count_documents() == 14962


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


def test_development_uses_complete_local_corpus_when_pinned_fts_is_ready(
    monkeypatch, tmp_path
):
    from pathlib import Path

    from app.services import legal_browser

    full_store_path = tmp_path / "full" / "content_store.sqlite3"
    full_fts_path = tmp_path / "full" / "legal_fts.sqlite3"
    v3_store_path = tmp_path / "v3" / "content_store.sqlite3"
    v3_fts_path = tmp_path / "v3" / "legal_fts.sqlite3"
    v3_body_path = tmp_path / "v3" / "legal_body_fts.sqlite3"
    for path in (full_store_path, full_fts_path, v3_store_path, v3_fts_path, v3_body_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    class Store:
        def __init__(self, path):
            self.path = Path(path)

    class Index:
        def __init__(self, *, store, path, dataset_revision):
            self.store = store
            self.path = Path(path)
            self.dataset_revision = dataset_revision

        def is_ready(self):
            return self.path == full_fts_path

    monkeypatch.setattr(legal_browser, "ContentStore", Store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", Index)
    monkeypatch.setattr(legal_browser, "BodySearchIndex", lambda path: Store(path))

    browser = legal_browser.LegalBrowser.from_settings(
        SimpleNamespace(
            APP_ENV="development",
            SERVERLESS_ONLINE_ONLY=False,
            USE_LEGACY_FREE_PIPELINE=False,
            CONTENT_STORE_PATH=full_store_path,
            LEGAL_FTS_PATH=full_fts_path,
            V3_CONTENT_STORE_PATH=v3_store_path,
            V3_LEGAL_FTS_PATH=v3_fts_path,
            DATASET_REVISION="pinned-revision",
        )
    )

    assert browser._store.path == full_store_path
    assert browser._index.path == full_fts_path
    assert browser._index.dataset_revision == "pinned-revision"
    assert browser._body_index.path == v3_body_path


def test_development_falls_back_to_v3_when_full_fts_is_not_ready(
    monkeypatch, tmp_path
):
    from pathlib import Path

    from app.services import legal_browser

    full_store_path = tmp_path / "full" / "content_store.sqlite3"
    full_fts_path = tmp_path / "full" / "legal_fts.sqlite3"
    v3_store_path = tmp_path / "v3" / "content_store.sqlite3"
    v3_fts_path = tmp_path / "v3" / "legal_fts.sqlite3"
    v3_body_path = tmp_path / "v3" / "legal_body_fts.sqlite3"
    for path in (full_store_path, full_fts_path, v3_store_path, v3_fts_path, v3_body_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    class Store:
        def __init__(self, path):
            self.path = Path(path)

    class Index:
        def __init__(self, *, store, path, dataset_revision):
            self.store = store
            self.path = Path(path)

        def is_ready(self):
            return False

    monkeypatch.setattr(legal_browser, "ContentStore", Store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", Index)
    monkeypatch.setattr(legal_browser, "BodySearchIndex", lambda path: Store(path))

    browser = legal_browser.LegalBrowser.from_settings(
        SimpleNamespace(
            APP_ENV="development",
            SERVERLESS_ONLINE_ONLY=False,
            USE_LEGACY_FREE_PIPELINE=False,
            CONTENT_STORE_PATH=full_store_path,
            LEGAL_FTS_PATH=full_fts_path,
            V3_CONTENT_STORE_PATH=v3_store_path,
            V3_LEGAL_FTS_PATH=v3_fts_path,
            DATASET_REVISION="pinned-revision",
        )
    )

    assert browser._store.path == v3_store_path
    assert browser._index.path == v3_fts_path
    assert browser._body_index.path == v3_body_path


def test_development_uses_supabase_when_local_corpus_is_missing(
    monkeypatch, tmp_path
):
    from app.services import legal_browser

    missing_content = tmp_path / "missing" / "content.sqlite3"
    missing_fts = tmp_path / "missing" / "fts.sqlite3"
    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=tmp_path / "full" / "content.sqlite3",
        LEGAL_FTS_PATH=tmp_path / "full" / "fts.sqlite3",
        V3_CONTENT_STORE_PATH=missing_content,
        V3_LEGAL_FTS_PATH=missing_fts,
        DATASET_REVISION="pinned-revision",
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test-key",
        QDRANT_FULL_DOC_BODY_SEARCH_ENABLED=True,
        QDRANT_URL="https://qdrant.example",
        QDRANT_API_KEY="test-key",
        QDRANT_FULL_DOC_BODY_COLLECTION="legal-body",
    )
    remote = object()
    body_index = object()

    monkeypatch.setattr(
        legal_browser,
        "SupabaseLegalStore",
        lambda **_kwargs: remote,
    )
    monkeypatch.setattr(
        legal_browser,
        "QdrantFullDocBodySearch",
        lambda **_kwargs: body_index,
    )
    monkeypatch.setattr(
        legal_browser,
        "ContentStore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing local SQLite must not be opened")
        ),
    )

    browser = legal_browser.LegalBrowser.from_settings(settings)

    assert browser._store is remote
    assert browser._index is remote
    assert browser._body_index is body_index
    assert not missing_content.exists()
    assert not missing_fts.exists()


def test_development_uses_supabase_when_local_fts_exists_but_is_invalid(
    tmp_path,
):
    from app.services.legal_browser import should_use_supabase_legal_store

    content_path = tmp_path / "content.sqlite3"
    fts_path = tmp_path / "legal_fts.sqlite3"
    content_path.touch()
    fts_path.touch()
    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=True,
        CONTENT_STORE_PATH=content_path,
        LEGAL_FTS_PATH=fts_path,
        V3_CONTENT_STORE_PATH=tmp_path / "v3-content.sqlite3",
        V3_LEGAL_FTS_PATH=tmp_path / "v3-fts.sqlite3",
        DATASET_REVISION="pinned-revision",
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="public-test-key",
    )

    assert should_use_supabase_legal_store(settings)


def test_supabase_fallback_requires_development_and_public_credentials(tmp_path):
    from app.services.legal_browser import should_use_supabase_legal_store

    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=tmp_path / "full-content.sqlite3",
        LEGAL_FTS_PATH=tmp_path / "full-fts.sqlite3",
        V3_CONTENT_STORE_PATH=tmp_path / "v3-content.sqlite3",
        V3_LEGAL_FTS_PATH=tmp_path / "v3-fts.sqlite3",
    )
    assert not should_use_supabase_legal_store(settings)

    settings.SUPABASE_URL = "https://project.supabase.co"
    settings.SUPABASE_PUBLISHABLE_KEY = "public-test-key"
    settings.APP_ENV = "test"
    assert not should_use_supabase_legal_store(settings)

    settings.APP_ENV = "development"
    assert should_use_supabase_legal_store(settings)


def _write_clean_derivative_metadata(
    clean_path,
    *,
    base_path,
    revision="pinned-revision",
    overlay_sha="a" * 64,
    overlay_count=189,
):
    import json
    import sqlite3

    with sqlite3.connect(clean_path) as db:
        db.execute("CREATE TABLE build_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        report = {
            "joined_count": 4,
            "metadata_count": 4,
            "content_count": 4,
            "average_sparse_document_length": 979.1241640033913,
        }
        metadata = {
            "status": "complete",
            "build_report": json.dumps(report),
            "raw_build_report": json.dumps(report),
            "clean_derivative_status": "complete",
            "clean_dataset_revision": revision,
            "clean_base_store_path": str(base_path.resolve()),
            "clean_overlay_manifest_sha256": overlay_sha,
            "clean_overlay_document_count": str(overlay_count),
            "clean_body_index_document_count": "4989",
            "clean_body_index_passage_count": "2",
            "clean_body_index_source_sha256": "b" * 64,
        }
        db.executemany("INSERT INTO build_metadata VALUES (?,?)", metadata.items())


def test_development_prefers_lineage_verified_clean_store_and_body_index(
    monkeypatch, tmp_path
):
    import sqlite3
    from pathlib import Path

    from app.services import legal_browser

    base = tmp_path / "raw" / "content.sqlite3"
    clean = tmp_path / "clean" / "content_store.sqlite3"
    raw_fts = tmp_path / "raw" / "legal_fts.sqlite3"
    body_path = clean.with_name("legal_body_fts.sqlite3")
    v3_store = tmp_path / "v3" / "content.sqlite3"
    v3_fts = tmp_path / "v3" / "legal_fts.sqlite3"
    v3_body = v3_store.with_name("legal_body_fts.sqlite3")
    for path in (base, clean, raw_fts, body_path, v3_store, v3_fts, v3_body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    _write_clean_derivative_metadata(clean, base_path=base)

    class Store:
        def __init__(self, path):
            self.path = Path(path)

        def build_report(self):
            return SimpleNamespace(joined_count=4)

    class Index:
        def __init__(self, *, store, path, dataset_revision):
            self.store = store
            self.path = Path(path)
            self.dataset_revision = dataset_revision

        def is_ready(self):
            return self.path == raw_fts

    class BodyIndex:
        def __init__(self, path):
            self.path = Path(path)

        def coverage(self):
            return {
                "schema_version": 1,
                "overlap_characters": 240,
                "document_count": 4989,
                "passage_count": 2,
                "source_sha256": "b" * 64,
            }

    monkeypatch.setattr(legal_browser, "ContentStore", Store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", Index)
    monkeypatch.setattr(legal_browser, "BodySearchIndex", BodyIndex)
    settings = SimpleNamespace(
        APP_ENV="development",
        SERVERLESS_ONLINE_ONLY=False,
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=base,
        CLEAN_CONTENT_STORE_PATH=clean,
        LEGAL_FTS_PATH=raw_fts,
        V3_CONTENT_STORE_PATH=v3_store,
        V3_LEGAL_FTS_PATH=v3_fts,
        DATASET_REVISION="pinned-revision",
        EXPECTED_DOCUMENT_COUNT=4,
        V3_AVERAGE_SPARSE_DOCUMENT_LENGTH=979.1241640033913,
    )

    browser = legal_browser.LegalBrowser.from_settings(settings)

    assert browser._store.path == clean
    assert browser._index.path == raw_fts
    assert browser._body_index.path == body_path
    with sqlite3.connect(clean) as db:
        db.execute(
            "UPDATE build_metadata SET value=? "
            "WHERE key='clean_body_index_source_sha256'",
            ("c" * 64,),
        )
    fallback = legal_browser.LegalBrowser.from_settings(settings)
    assert fallback._store.path == clean
    assert fallback._body_index.path == v3_body


def test_clean_content_store_setting_defaults_to_separate_v1_derivative():
    from pathlib import Path

    from app.config import Settings

    assert Settings.model_fields["CLEAN_CONTENT_STORE_PATH"].default == Path(
        "data/huggingface/clean-v1/content_store.sqlite3"
    )


def test_clean_derivative_wrong_lineage_never_supersedes_raw_store(
    monkeypatch, tmp_path
):
    import sqlite3
    from pathlib import Path

    from app.services import legal_browser

    base = tmp_path / "raw" / "content.sqlite3"
    clean = tmp_path / "clean" / "content_store.sqlite3"
    raw_fts = tmp_path / "raw" / "legal_fts.sqlite3"
    v3_store = tmp_path / "v3" / "content.sqlite3"
    v3_fts = tmp_path / "v3" / "legal_fts.sqlite3"
    for path in (base, clean, raw_fts, v3_store, v3_fts):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    _write_clean_derivative_metadata(clean, base_path=base, revision="other-revision")

    class Store:
        def __init__(self, path):
            self.path = Path(path)

        def build_report(self):
            return SimpleNamespace(joined_count=4)

    class Index:
        def __init__(self, *, store, path, dataset_revision):
            self.path = Path(path)

        def is_ready(self):
            return self.path == raw_fts

    monkeypatch.setattr(legal_browser, "ContentStore", Store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", Index)
    settings = SimpleNamespace(
        APP_ENV="development",
        USE_LEGACY_FREE_PIPELINE=False,
        CONTENT_STORE_PATH=base,
        CLEAN_CONTENT_STORE_PATH=clean,
        LEGAL_FTS_PATH=raw_fts,
        V3_CONTENT_STORE_PATH=v3_store,
        V3_LEGAL_FTS_PATH=v3_fts,
        DATASET_REVISION="pinned-revision",
        EXPECTED_DOCUMENT_COUNT=4,
        V3_AVERAGE_SPARSE_DOCUMENT_LENGTH=979.1241640033913,
    )

    assert legal_browser.local_legal_paths(settings) == (base, raw_fts, True)
    with sqlite3.connect(clean) as db:
        db.execute(
            "UPDATE build_metadata SET value=? WHERE key='clean_base_store_path'",
            (str(base.resolve()),),
        )
        db.execute(
            "UPDATE build_metadata SET value=? "
            "WHERE key='clean_overlay_document_count'",
            ("188",),
        )
    assert legal_browser.local_legal_paths(settings) == (base, raw_fts, True)
    with sqlite3.connect(clean) as db:
        db.execute(
            "UPDATE build_metadata SET value=? WHERE key='clean_dataset_revision'",
            ("pinned-revision",),
        )
        db.execute(
            "UPDATE build_metadata SET value=? WHERE key='clean_base_store_path'",
            (str((tmp_path / "other-base.sqlite3").resolve()),),
        )
    assert legal_browser.local_legal_paths(settings) == (base, raw_fts, True)


def test_legacy_local_paths_remain_raw_with_clean_derivative_present(
    monkeypatch, tmp_path
):
    from pathlib import Path

    from app.services import legal_browser

    base = tmp_path / "raw.sqlite3"
    clean = tmp_path / "clean.sqlite3"
    raw_fts = tmp_path / "raw-fts.sqlite3"
    v3_store = tmp_path / "v3.sqlite3"
    v3_fts = tmp_path / "v3-fts.sqlite3"
    for path in (base, clean, raw_fts, v3_store, v3_fts):
        path.touch()
    _write_clean_derivative_metadata(clean, base_path=base)

    class Store:
        def __init__(self, path):
            self.path = Path(path)

    class Index:
        def __init__(self, *, store, path, dataset_revision):
            self.path = Path(path)

        def is_ready(self):
            return True

    monkeypatch.setattr(legal_browser, "ContentStore", Store)
    monkeypatch.setattr(legal_browser, "LegalFtsIndex", Index)
    settings = SimpleNamespace(
        APP_ENV="development",
        USE_LEGACY_FREE_PIPELINE=True,
        CONTENT_STORE_PATH=base,
        CLEAN_CONTENT_STORE_PATH=clean,
        LEGAL_FTS_PATH=raw_fts,
        V3_CONTENT_STORE_PATH=v3_store,
        V3_LEGAL_FTS_PATH=v3_fts,
        DATASET_REVISION="pinned-revision",
        EXPECTED_DOCUMENT_COUNT=4,
        V3_AVERAGE_SPARSE_DOCUMENT_LENGTH=979.1241640033913,
    )

    assert legal_browser.local_legal_paths(settings) == (base, raw_fts, True)


def test_supabase_metadata_search_uses_bounded_offset():
    from app.services.legal_browser import SupabaseLegalStore

    requests = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=[])))
    store = SupabaseLegalStore(url="https://project.supabase.co", publishable_key="test", client=client)

    store.search("Bo luat", limit=21, offset=20)

    assert requests[0].url.params["limit"] == "21"
    assert requests[0].url.params["offset"] == "20"


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


def test_local_full_number_filters_before_limit(tmp_path):
    import sqlite3
    from app.services.legal_browser import LegalBrowser, SearchFilters
    store = _Store()
    store.metadata[1] = SimpleNamespace(**{**store.metadata[7].__dict__, "document_id": 1, "document_number": "68/2006/TT-BXD", "title": "68/2026/TT-BXD", "legal_type": "Khác"})
    store.metadata[2] = SimpleNamespace(**{**store.metadata[7].__dict__, "document_id": 2, "legal_type": "Khác"})
    store.path = tmp_path / "content.sqlite3"
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TABLE metadata(document_id INTEGER, document_number TEXT, title TEXT, legal_type TEXT, issuing_authority TEXT, issuance_date TEXT)")
        connection.execute("INSERT INTO metadata VALUES(1,'68/2006/TT-BXD','68/2026/TT-BXD','Khác','','2026-01-01')")
        connection.execute("INSERT INTO metadata VALUES(2,'45/2019/QH14','Bộ luật Lao động 2019','Khác','','2019-01-01')")
        connection.execute("INSERT INTO metadata VALUES(7,'45/2019/QH14','Bộ luật Lao động 2019','Bộ luật','Quốc hội','2019-11-20')")
    browser = LegalBrowser(store=store, index=_Index([]))
    assert browser.search("68/2026/TT-BXD", limit=1, filters=SearchFilters(sort="newest")) == []
    assert [row.document_id for row in browser.search("45/2019/QH14", limit=1, filters=SearchFilters(legal_type="Bộ luật"))] == [7]


def test_supabase_full_number_uses_number_only_before_limit():
    from app.services.legal_browser import SupabaseLegalStore, SearchFilters
    requests = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=[])))
    store = SupabaseLegalStore(url="https://project.supabase.co", publishable_key="test", client=client)
    store.search("Theo số 68/2026/TT-BXD", limit=1, filters=SearchFilters(legal_type="Bộ luật", sort="newest"))
    params = requests[0].url.params
    assert params["document_number"] == "ilike.68/2026/TT-BXD"
    assert "or" not in params
    assert params["legal_type"] == "eq.Bộ luật"
    assert params["limit"] == "1"


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
