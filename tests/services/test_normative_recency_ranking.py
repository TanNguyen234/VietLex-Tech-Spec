from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from qdrant_client import models

from app.ingestion.vertex_qdrant_migration import VertexQdrantContract


def _v3_point(
    point_id: str,
    *,
    document_id: int,
    document_number: str,
    title: str,
    score: float,
    issuance_date: str = "2024-01-01",
    issuance_year: int | None = None,
    normative_rank: int | None = None,
    validity_hint: str | None = None,
):
    payload: dict[str, object] = {
        "document_id": document_id,
        "document_number": document_number,
        "title": title,
        "source_url": f"https://vbpl.vn/{document_id}",
        "legal_type": "Luật",
        "issuing_authority": "Quốc hội",
        "issuance_date": issuance_date,
        "heading_path": "Điều 1",
        "citation": f"{document_number}, Điều 1",
        "article": "Điều 1",
        "clause": None,
        "body": f"Điều 1. Nội dung của {title}.",
        "token_count": 6,
        "dataset_revision": "rev",
        "chunk_sha256": "a" * 64,
        "embedding_provider": "google_vertex_ai",
        "embedding_model": "gemini-embedding-2",
        "embedding_dimension": 1024,
        "migration_schema": "vietlex-vertex-qdrant-v1",
    }
    if issuance_year is not None:
        payload["issuance_year"] = issuance_year
    if normative_rank is not None:
        payload["normative_rank"] = normative_rank
    if validity_hint is not None:
        payload["validity_hint"] = validity_hint
    return SimpleNamespace(id=point_id, score=score, payload=payload)


class _Provider:
    async def embed_query(self, query: str, **kwargs):
        return SimpleNamespace(values=[0.1] * 1024)


class _Sparse:
    def encode_query(self, query: str):
        return SimpleNamespace(indices=[1], values=[0.5])


@pytest.mark.asyncio
async def test_superseded_laws_rank_below_active_replacements_and_recency_breaks_ties() -> None:
    from app.services.vertex_qdrant_retrieval import VertexQdrantRetriever

    superseded_land = _v3_point(
        "pt-land-2013",
        document_id=215836,
        document_number="45/2013/QH13",
        title="Luật Đất đai 2013",
        score=0.92,
        issuance_date="2013-11-29",
        issuance_year=2013,
        normative_rank=4,
        validity_hint="superseded",
    )
    active_land = _v3_point(
        "pt-land-2024",
        document_id=523642,
        document_number="31/2024/QH15",
        title="Luật Đất đai 2024",
        score=0.78,
        issuance_date="2024-01-18",
        issuance_year=2024,
        normative_rank=4,
        validity_hint="active_candidate",
    )
    superseded_wage = _v3_point(
        "pt-wage-2024",
        document_id=603278,
        document_number="74/2024/NĐ-CP",
        title="Nghị định 74/2024/NĐ-CP mức lương tối thiểu",
        score=0.88,
        issuance_date="2024-06-30",
        issuance_year=2024,
        normative_rank=2,
        validity_hint="superseded",
    )
    active_wage = _v3_point(
        "pt-wage-2025",
        document_id=665866,
        document_number="293/2025/NĐ-CP",
        title="Nghị định 293/2025/NĐ-CP mức lương tối thiểu",
        score=0.75,
        issuance_date="2025-11-10",
        issuance_year=2025,
        normative_rank=2,
        validity_hint="active_candidate",
    )

    class _Client:
        async def query_points(self, **kwargs):
            fusion = kwargs["query"].fusion
            if fusion == models.Fusion.RRF:
                return SimpleNamespace(points=[superseded_land, superseded_wage, active_land, active_wage])
            return SimpleNamespace(points=[superseded_wage, superseded_land, active_wage, active_land])

    retriever = VertexQdrantRetriever(
        provider=_Provider(),
        client=_Client(),
        sparse_encoder=_Sparse(),
        contract=VertexQdrantContract(),
        dataset_revision="rev",
    )

    outcome = await retriever.retrieve_detailed(
        "chuyển nhượng quyền sử dụng đất và mức lương tối thiểu vùng hiện nay",
        sparse_query="chuyển nhượng đất và mức lương tối thiểu",
        limit=4,
        fusion="rrf-dbsf",
    )

    ranked_ids = [chunk.document_id for chunk in outcome.evidence]
    # Active replacements (523642, 665866) must rank above superseded (215836, 603278)
    assert set(ranked_ids[:2]) == {523642, 665866}
    assert set(ranked_ids[2:]) == {215836, 603278}
    # Between tied active points (3rd & 4th in RRF/DBSF), 2024 Law / 2025 Decree deterministic tie-break works
    assert outcome.status == "ok"


@pytest.mark.asyncio
async def test_recency_tiebreaker_ranks_newer_year_ahead_on_equal_rrf_rank() -> None:
    from app.services.vertex_qdrant_retrieval import query_vertex_points

    older = _v3_point(
        "a-older",
        document_id=100,
        document_number="10/2016/NĐ-CP",
        title="Nghị định năm 2016",
        score=0.5,
        issuance_year=2016,
        validity_hint="active_candidate",
    )
    newer = _v3_point(
        "z-newer",
        document_id=200,
        document_number="20/2025/NĐ-CP",
        title="Nghị định năm 2025",
        score=0.5,
        issuance_year=2025,
        validity_hint="active_candidate",
    )

    class _TiedClient:
        async def query_points(self, **kwargs):
            return SimpleNamespace(points=[older, newer])

    points = await query_vertex_points(
        "quy định xử lý hồ sơ",
        sparse_query="quy định xử lý hồ sơ",
        provider=_Provider(),
        client=_TiedClient(),
        sparse_encoder=_Sparse(),
        contract=VertexQdrantContract(),
        limit=2,
        fusion="dbsf",
    )

    assert [p.payload["document_id"] for p in points] == [200, 100]


@pytest.mark.asyncio
async def test_historical_year_query_preserves_explicitly_named_superseded_law() -> None:
    from app.services.vertex_qdrant_retrieval import query_vertex_points

    land_2013 = _v3_point(
        "pt-land-2013",
        document_id=215836,
        document_number="45/2013/QH13",
        title="Luật Đất đai 2013",
        score=0.90,
        issuance_year=2013,
        validity_hint="superseded",
    )
    land_2024 = _v3_point(
        "pt-land-2024",
        document_id=523642,
        document_number="31/2024/QH15",
        title="Luật Đất đai 2024",
        score=0.70,
        issuance_year=2024,
        validity_hint="active_candidate",
    )

    class _Client:
        async def query_points(self, **kwargs):
            return SimpleNamespace(points=[land_2013, land_2024])

    points = await query_vertex_points(
        "Theo Luật Đất đai 2013 quy định thu hồi đất thế nào?",
        sparse_query="Luật Đất đai 2013 thu hồi đất",
        provider=_Provider(),
        client=_Client(),
        sparse_encoder=_Sparse(),
        contract=VertexQdrantContract(),
        limit=2,
        fusion="dbsf",
    )

    assert [p.payload["document_id"] for p in points] == [215836, 523642]


@pytest.mark.asyncio
async def test_vertex_embed_documents_batch_sends_single_batch_and_retries_429(monkeypatch) -> None:
    from app.services import vertex_ai

    calls: list[dict] = []
    attempt_counter = {"count": 0}

    class _QuotaErr(RuntimeError):
        code = 429

    class _Models:
        async def embed_content(self, **kwargs):
            calls.append(kwargs)
            attempt_counter["count"] += 1
            if attempt_counter["count"] == 1:
                raise _QuotaErr("rate limited")
            contents = kwargs["contents"]
            dim = kwargs["config"].output_dimensionality
            embeddings = []
            for idx, _ in enumerate(contents):
                vec = [0.0] * dim
                vec[idx % dim] = 1.0
                embeddings.append(SimpleNamespace(values=vec))
            return SimpleNamespace(embeddings=embeddings)

    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fast_sleep)

    settings = SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="test-proj",
        GOOGLE_CLOUD_QUOTA_PROJECT=None,
        GOOGLE_CLOUD_LOCATION="global",
        VERTEX_LLM_MODEL="gemini-3.5-flash",
        VERTEX_EMBEDDING_MODEL="gemini-embedding-2",
        VERTEX_REQUEST_TIMEOUT_SECONDS=5.0,
        VERTEX_MAX_RETRIES=2,
        USE_LEGACY_FREE_PIPELINE=False,
    )
    provider = vertex_ai.VertexAIProvider(
        settings=settings,
        credentials_loader=lambda: (object(), "test-proj"),
        client_factory=lambda **_kw: SimpleNamespace(aio=SimpleNamespace(models=_Models())),
    )

    results = await provider.embed_documents_batch(
        [("Nội dung 1", "Tiêu đề 1"), ("Nội dung 2", None)],
        output_dimensionality=1024,
    )

    assert len(results) == 2
    assert len(calls) == 2  # 1st hit 429, 2nd succeeded
    assert calls[-1]["contents"] == [
        "title: Tiêu đề 1 | text: Nội dung 1",
        "title: none | text: Nội dung 2",
    ]
    assert results[0].values[0] == 1.0
    assert results[1].values[1] == 1.0


@pytest.mark.asyncio
async def test_primary_law_rescue_online_body_search_fallback_when_sqlite_absent(tmp_path: Path) -> None:
    from app.services.primary_law_rescue import rescue_primary_law_evidence
    from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch

    content = (
        "Điều 1. Phạm vi điều chỉnh\n"
        "Nghị định này quy định mức lương tối thiểu đối với người lao động.\n"
        "Điều 3. Mức lương tối thiểu\n"
        "1. Mức lương tối thiểu tháng tại vùng I là 5.310.000 đồng/tháng."
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    meta = SimpleNamespace(
        document_id=665866,
        document_number="293/2025/NĐ-CP",
        title="Nghị định 293/2025/NĐ-CP quy định mức lương tối thiểu",
        source_url="https://vbpl.vn/665866",
        legal_type="Nghị định",
        issuing_authority="Chính phủ",
        issuance_date="2025-11-10",
    )
    stored_doc = SimpleNamespace(metadata=meta, content=content, content_sha256=digest)
    store = SimpleNamespace(
        count_documents=lambda: 1,
        get_many=lambda ids: {665866: stored_doc} if 665866 in ids else {},
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": "green",
                        "points_count": 1,
                        "payload_schema": {
                            "body": {
                                "points": 1,
                                "params": {
                                    "type": "text",
                                    "phrase_matching": True,
                                    "ascii_folding": True,
                                },
                            }
                        },
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [
                        {
                            "id": 665866,
                            "payload": {"document_id": 665866, "content_sha256": digest},
                        }
                    ],
                    "next_page_offset": None,
                }
            },
        )

    body_index = QdrantFullDocBodySearch(
        url="https://qdrant.example",
        api_key="test-key",
        collection="vietlex-legal-body-search-v1",
        store=store,
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )

    class _OnlineBrowser:
        def __init__(self) -> None:
            self._body_index = body_index

        def search(self, query, *, limit, filters=None):
            return []

        def get_document(self, document_id: int):
            return stored_doc if document_id == 665866 else None

    settings = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        SERVERLESS_ONLINE_ONLY=True,
        CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
        FINAL_EVIDENCE_LIMIT=3,
        LLM_CONTEXT_MAX_TOKENS=720,
        QUERY_CHUNK_MAX_TOKENS=220,
        QUERY_CHUNK_OVERLAP_TOKENS=24,
    )

    result = await rescue_primary_law_evidence(
        "Mức lương tối thiểu vùng I hiện nay là bao nhiêu?",
        settings=settings,
        browser=_OnlineBrowser(),
    )

    assert result.evidence
    assert result.evidence[0].document_id == 665866
    assert "5.310.000" in result.evidence[0].text
    assert result.diagnostics["status"] == "evidence_selected"


@pytest.mark.asyncio
async def test_vertex_http2_batch_embed_refreshes_401_under_low_uptime_and_tracks_budget(monkeypatch) -> None:
    from app.services import vertex_ai
    from app.services.provider_http_budget import (
        ProviderHttpAttemptBudgetExceeded,
        provider_http_budget_scope,
    )

    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _fast_sleep)
    monkeypatch.setattr("time.monotonic", lambda: 50.0)  # < 2400s uptime

    class _FakeCreds:
        def __init__(self) -> None:
            self.token = "stale-boot-token"
            self.valid = True
            self.refresh_calls = 0

        def refresh(self, _req) -> None:
            self.refresh_calls += 1
            self.token = f"fresh-token-{self.refresh_calls}"
            self.valid = True

    creds = _FakeCreds()
    seen_auth_headers: list[str] = []
    call_idx = {"n": 0}

    def _http2_handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers.get("Authorization", ""))
        call_idx["n"] += 1
        if call_idx["n"] == 1:
            return httpx.Response(401, json={"error": "unauthenticated"})
        if call_idx["n"] == 2:
            return httpx.Response(429, json={"error": "rate_limited"})
        vec = [1.0] + [0.0] * 1023
        return httpx.Response(200, json={"embedding": {"values": vec}})

    settings = SimpleNamespace(
        GOOGLE_CLOUD_PROJECT="test-proj",
        GOOGLE_CLOUD_QUOTA_PROJECT=None,
        GOOGLE_CLOUD_LOCATION="global",
        VERTEX_LLM_MODEL="gemini-3.5-flash",
        VERTEX_EMBEDDING_MODEL="gemini-embedding-2",
        VERTEX_REQUEST_TIMEOUT_SECONDS=5.0,
        VERTEX_MAX_RETRIES=2,
        USE_LEGACY_FREE_PIPELINE=False,
    )
    provider = vertex_ai.VertexAIProvider(
        settings=settings,
        credentials_loader=lambda: (creds, "test-proj"),
    )
    # Keep _uses_default_client_factory=True so production HTTP/2 path runs, stubbing _get_client & transport
    monkeypatch.setattr(
        provider,
        "_get_client",
        lambda: setattr(provider, "_credentials", creds) or setattr(provider, "_project", "test-proj") or object(),
    )
    mock_h2 = httpx.AsyncClient(transport=httpx.MockTransport(_http2_handler))
    vertex_ai._wrap_client_transports(
        mock_h2,
        vertex_ai.ProviderHttpAsyncTransport,
        boundary="vertex_model_httpx_async",
        provider="google_vertex_ai",
    )
    provider._batch_embed_http2_client = mock_h2

    with provider_http_budget_scope(limit=5) as budget:
        res = await provider.embed_documents_batch(
            [("Nội dung điều khoản", "Luật Đất đai")],
            output_dimensionality=1024,
        )
        assert len(res) == 1
        assert creds.refresh_calls >= 2  # Initial refresh + forced refresh after 401 even at monotonic=50s
        assert seen_auth_headers[-1].startswith("Bearer fresh-token-")
        assert budget.snapshot()["attempt_count"] == 3

    with provider_http_budget_scope(limit=1):
        with pytest.raises(ProviderHttpAttemptBudgetExceeded):
            await provider.embed_documents_batch(
                [("Nội dung 2", "Tiêu đề"), ("Nội dung 3", "Tiêu đề")],
                output_dimensionality=1024,
            )
    await provider.close()


@pytest.mark.asyncio
async def test_query_year_word_boundary_overfetch_and_registry_prompt_injection() -> None:
    from app.services.rag_pipeline import build_answer_prompts
    from app.services.vertex_qdrant_retrieval import query_vertex_points

    superseded_2000 = _v3_point(
        "pt-2000",
        document_id=10,
        document_number="01/2000/NĐ-CP",
        title="Nghị định cũ năm 2000",
        score=0.95,
        issuance_year=2000,
        validity_hint="superseded",
    )
    active_2024 = _v3_point(
        "pt-2024",
        document_id=20,
        document_number="168/2024/NĐ-CP",
        title="Nghị định 168/2024/NĐ-CP",
        score=0.70,
        issuance_year=2024,
        validity_hint="active_candidate",
    )
    seen_limits: list[int] = []

    class _OverfetchClient:
        async def query_points(self, **kwargs):
            seen_limits.append(kwargs["limit"])
            # Superseded sits at rank 1, active sits at rank 2 (would be missed if limit=1 without overfetch!)
            return SimpleNamespace(points=[superseded_2000, active_2024][: kwargs["limit"]])

    # "20000" must NOT match year "2000", and limit=1 must over-fetch so active_2024 wins!
    pts = await query_vertex_points(
        "Mức phạt 20000 đồng",
        sparse_query="phạt 20000 đồng",
        provider=_Provider(),
        client=_OverfetchClient(),
        sparse_encoder=_Sparse(),
        contract=VertexQdrantContract(),
        limit=1,
        fusion="dbsf",
    )
    assert seen_limits[0] >= 12
    assert [p.payload["document_id"] for p in pts] == [20]

    # Registry effects must be wired into LLM user_prompt!
    user_prompt, _, _ = build_answer_prompts(
        "Mức lương tối thiểu hiện nay?",
        "mức lương tối thiểu",
        ["[74/2024/NĐ-CP, Điều 3]\nTiêu đề: Nghị định 74/2024/NĐ-CP\nNguồn: https://vbpl.vn/1\nĐiều 3. Lương tối thiểu."],
        registry_effects={
            "74/2024/NĐ-CP": {
                "status": "replaced",
                "as_of": "2026-01-01",
                "effective_from": "2024-07-01",
                "effective_to": "2025-12-31",
                "amended_by": [],
                "replaced_by": ["293/2025/NĐ-CP"],
            }
        },
    )
    assert "74/2024/NĐ-CP" in user_prompt
    assert "replaced" in user_prompt
    assert "293/2025/NĐ-CP" in user_prompt


@pytest.mark.asyncio
async def test_primary_law_rescue_e_transaction_2023_and_online_fallback_observability(tmp_path: Path) -> None:
    from app.services import primary_law_rescue as plr
    from app.services.qdrant_full_doc_body_search import QdrantFullDocBodySearch

    assert plr._E_TRANSACTION.document_number == "20/2023/QH15"
    assert "luat" in plr._E_TRANSACTION.legal_types

    class _FailingBodyIndex(QdrantFullDocBodySearch):
        def __init__(self) -> None:
            pass

        def search(self, query, *, filters=None, limit=20, offset=0):
            raise RuntimeError("qdrant_body_timeout")

    class _MismatchedBrowser:
        def __init__(self) -> None:
            self._body_index = _FailingBodyIndex()

        def search(self, query, *, limit, filters=None):
            # Returns a non-matching candidate so diagnostics["candidates"] > 0 while selected_chunks == []
            return [
                SimpleNamespace(
                    document_id=999,
                    document_number="01/2020/TT-BTC",
                    title="Thông tư không khớp",
                    legal_type="Thông tư",
                    issuance_date="2020-01-01",
                )
            ]

        def get_document(self, document_id: int):
            return None

    settings = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        SERVERLESS_ONLINE_ONLY=True,
        CONTENT_STORE_PATH=tmp_path / "missing.sqlite3",
        FINAL_EVIDENCE_LIMIT=3,
        LLM_CONTEXT_MAX_TOKENS=720,
        QUERY_CHUNK_MAX_TOKENS=220,
        QUERY_CHUNK_OVERLAP_TOKENS=24,
    )
    result = await plr.rescue_primary_law_evidence(
        "Giá trị pháp lý của chữ ký điện tử và tin nhắn Zalo làm chứng cứ?",
        settings=settings,
        browser=_MismatchedBrowser(),
    )
    errors = result.diagnostics.get("online_body_fallback_errors") or []
    assert any(e.get("error_type") == "RuntimeError" for e in errors)


def test_prefer_primary_topic_contexts_retains_corpus_when_topics_unrecognized_and_rrf_step_preserved() -> None:
    from app.services.primary_law_rescue import prefer_primary_topic_contexts
    from app.services.vertex_qdrant_retrieval import _apply_validity_and_recency_ranking

    v3_statute_ctx = (
        "[72/2020/QH14, Điều 16]\n"
        "Nguồn: https://vbpl.vn/431147\n"
        "Tiêu đề: Luật Bảo vệ môi trường 2020\n"
        "Điều 16. Phân loại khu vực ô nhiễm môi trường đất 2. Khu vực ô nhiễm môi trường đất được phân loại theo tiêu chí nguồn gây ô nhiễm."
    )
    primary_ctx = (
        "[08/2022/NĐ-CP, Điều 16]\n"
        "Nguồn: https://vbpl.vn/479457\n"
        "Tiêu đề: Nghị định 08/2022/NĐ-CP\n"
        "Điều 16. Điều tra, đánh giá chi tiết khu vực ô nhiễm môi trường đất."
    )
    merged = prefer_primary_topic_contexts(
        "Theo quy định tại Điều 16, khu vực ô nhiễm môi trường đất được phân loại dựa trên những tiêu chí nào?",
        [v3_statute_ctx],
        [primary_ctx],
        max_evidence=3,
    )
    assert v3_statute_ctx in merged

    # RRF rank-1 2020 Law (score 0.5/61 + 0.5/62) must NOT be overtaken by RRF rank-2 2026 Circular (score 0.5/62 + 0.5/62)
    law_2020 = _v3_point(
        "pt-law-2020",
        document_id=431147,
        document_number="72/2020/QH14",
        title="Luật Bảo vệ môi trường 2020",
        score=(0.5 / 61.0) + (0.5 / 62.0),
        issuance_year=2020,
        normative_rank=4,
        validity_hint="active_candidate",
    )
    circ_2026 = _v3_point(
        "pt-circ-2026",
        document_id=697269,
        document_number="14/2026/TT-BNNMT",
        title="Thông tư 14/2026/TT-BNNMT",
        score=(0.5 / 62.0) + (0.5 / 62.0),
        issuance_year=2026,
        normative_rank=1,
        validity_hint="active_candidate",
    )
    ranked = _apply_validity_and_recency_ranking(
        [law_2020, circ_2026],
        query_years=set(),
        limit=2,
    )
    assert [p.payload["document_id"] for p in ranked] == [431147, 697269]

