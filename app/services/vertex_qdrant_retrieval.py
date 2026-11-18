from __future__ import annotations

import copy
import re
import time
from typing import Any

from qdrant_client import models

from app.evaluation.schemas import RetrievalStageTrace, StageCandidate
from app.ingestion.legal_text import EvidenceChunk
from app.ingestion.vertex_qdrant_migration import VertexQdrantContract
from app.services.instrument_registry import SUPERSEDED_INSTRUMENTS
from app.services.legal_topic_terms import fold_topic_text
from app.services.retrieval import RetrievalOutcome

_QUERY_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_HEADER_YEAR_RE = re.compile(r"\d{1,4}/((?:19|20)\d{2})/")


def _is_point_superseded_for_query(payload: dict[str, Any], query_years: set[str]) -> bool:
    raw_year = payload.get("issuance_year")
    doc_year = (
        int(raw_year)
        if isinstance(raw_year, int) and not isinstance(raw_year, bool)
        else None
    )
    if doc_year is None:
        idate = payload.get("issuance_date")
        if isinstance(idate, str) and len(idate) >= 4 and idate[:4].isdecimal():
            doc_year = int(idate[:4])

    if doc_year is not None and str(doc_year) in query_years:
        return False

    if payload.get("validity_hint") == "superseded":
        return True

    header = fold_topic_text(
        f"{payload.get('document_number', '')} {payload.get('title', '')}"
    )
    if not header:
        return False
    if doc_year is None:
        match = _HEADER_YEAR_RE.search(header)
        doc_year = int(match.group(1)) if match else None
    for item in SUPERSEDED_INSTRUMENTS:
        if any(marker in header for marker in item.markers):
            if item.before_year:
                if (
                    doc_year is not None
                    and doc_year < int(item.before_year)
                    and str(doc_year) not in query_years
                ):
                    return True
            elif item.year not in query_years:
                return True
    return False


def _apply_validity_and_recency_ranking(
    points: list[object],
    *,
    query_years: set[str],
    limit: int,
) -> list[object]:
    adjusted: list[tuple[bool, object]] = []
    any_modified = False
    for point in points:
        payload = getattr(point, "payload", None) or {}
        if not isinstance(payload, dict):
            adjusted.append((False, point))
            continue
        base_score = float(getattr(point, "score", 0.0))
        superseded = _is_point_superseded_for_query(payload, query_years)
        raw_year = payload.get("issuance_year")
        has_year = isinstance(raw_year, int) and not isinstance(raw_year, bool)
        raw_rank = payload.get("normative_rank")
        has_rank = isinstance(raw_rank, int) and not isinstance(raw_rank, bool)

        if not superseded and not has_year and not has_rank:
            adjusted.append((False, point))
            continue

        any_modified = True
        new_score = base_score
        if superseded:
            new_score = base_score * 0.25 - 0.01
        if has_rank:
            new_score += 1e-5 * max(0, min(int(raw_rank), 6))
        if has_year:
            new_score += 2e-6 * max(0, min(int(raw_year) - 2000, 30)) / 30.0

        ranked_point = copy.copy(point)
        ranked_point.score = new_score
        adjusted.append((True, ranked_point))

    if not any_modified:
        return points[:limit]

    only_points = [item[1] for item in adjusted]
    return sorted(
        only_points,
        key=lambda pt: (-float(getattr(pt, "score", 0.0)), str(getattr(pt, "id", ""))),
    )[:limit]


async def query_vertex_points(
    dense_query: str,
    *,
    sparse_query: str,
    provider: object,
    client: object,
    sparse_encoder: object,
    contract: VertexQdrantContract,
    limit: int,
    fusion: str = "rrf",
) -> list[object]:
    dense_query = " ".join(dense_query.split())
    sparse_query = " ".join(sparse_query.split())
    if not dense_query or not sparse_query or limit <= 0:
        raise ValueError("queries must be nonblank and limit must be positive")
    dense = await provider.embed_query(
        dense_query,
        output_dimensionality=contract.vector_size,
        task="question_answering",
    )
    sparse = sparse_encoder.encode_query(sparse_query)
    prefetch_limit = max(20, limit * 4)
    internal_limit = max(limit, min(prefetch_limit, 12))
    fusion_mode = {
        "rrf": models.Fusion.RRF,
        "dbsf": models.Fusion.DBSF,
    }.get(fusion)
    if fusion_mode is None and fusion != "rrf-dbsf":
        raise ValueError(f"unsupported fusion mode: {fusion}")

    prefetch = [
            models.Prefetch(
                query=list(dense.values),
                using=contract.dense_vector_name,
                limit=prefetch_limit,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(sparse.indices),
                    values=list(sparse.values),
                ),
                using=contract.sparse_vector_name,
                limit=prefetch_limit,
            ),
        ]

    async def query_with(mode: models.Fusion) -> list[object]:
        response = await client.query_points(
            collection_name=contract.collection_name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=mode),
            limit=internal_limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(response.points)

    query_years = set(_QUERY_YEAR_RE.findall(f"{dense_query} {sparse_query}"))

    if fusion_mode is not None:
        raw_points = await query_with(fusion_mode)
        return _apply_validity_and_recency_ranking(
            raw_points,
            query_years=query_years,
            limit=limit,
        )

    rrf_points = await query_with(models.Fusion.RRF)
    dbsf_points = await query_with(models.Fusion.DBSF)
    point_by_id = {
        str(getattr(point, "id")): point
        for point in (*rrf_points, *dbsf_points)
    }
    missing_rank = internal_limit + 1
    rrf_rank = {
        str(getattr(point, "id")): rank
        for rank, point in enumerate(rrf_points, start=1)
    }
    dbsf_rank = {
        str(getattr(point, "id")): rank
        for rank, point in enumerate(dbsf_points, start=1)
    }
    blended = []
    for point_id, point in point_by_id.items():
        score = 0.5 / (60 + rrf_rank.get(point_id, missing_rank))
        score += 0.5 / (60 + dbsf_rank.get(point_id, missing_rank))
        ranked_point = copy.copy(point)
        ranked_point.score = score
        blended.append(ranked_point)
    sorted_blended = sorted(
        blended,
        key=lambda point: (-float(getattr(point, "score")), str(getattr(point, "id"))),
    )
    return _apply_validity_and_recency_ranking(
        sorted_blended,
        query_years=query_years,
        limit=limit,
    )


class VertexQdrantRetriever:
    def __init__(
        self,
        *,
        provider: object,
        client: object,
        sparse_encoder: object,
        contract: VertexQdrantContract,
        dataset_revision: str,
    ) -> None:
        self.provider = provider
        self.client = client
        self.sparse_encoder = sparse_encoder
        self.contract = contract
        self.dataset_revision = dataset_revision

    def _evidence(self, point: object) -> tuple[EvidenceChunk, StageCandidate]:
        payload: dict[str, Any] = dict(getattr(point, "payload", None) or {})
        expected = {
            "embedding_provider": "google_vertex_ai",
            "embedding_model": self.contract.embedding_model,
            "embedding_dimension": self.contract.vector_size,
            "migration_schema": "vietlex-vertex-qdrant-v1",
            "dataset_revision": self.dataset_revision,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise ValueError(f"invalid v3 payload {key}")
        required_nonblank = (
            "document_id",
            "document_number",
            "title",
            "source_url",
            "citation",
            "body",
            "token_count",
            "chunk_sha256",
        )
        missing = [
            key for key in required_nonblank if payload.get(key) in {None, ""}
        ]
        if "heading_path" not in payload:
            missing.append("heading_path")
        if missing:
            raise ValueError(f"missing v3 payload fields: {', '.join(missing)}")
        evidence = EvidenceChunk(
            document_id=int(payload["document_id"]),
            document_number=str(payload["document_number"]),
            title=str(payload["title"]),
            source_url=str(payload["source_url"]),
            heading_path=str(payload["heading_path"]),
            article=payload.get("article"),
            clause=payload.get("clause"),
            citation=str(payload["citation"]),
            text=str(payload["body"]),
            token_count=int(payload["token_count"]),
            source_content_sha256=(
                str(payload["content_sha256"])
                if payload.get("content_sha256")
                else None
            ),
        )
        candidate = StageCandidate(
            document_id=evidence.document_id,
            document_number=evidence.document_number,
            title=evidence.title,
            source_url=evidence.source_url,
            citation=evidence.citation,
            article=evidence.article,
            clause=evidence.clause,
            text=evidence.text,
            score=float(getattr(point, "score", 0.0)),
            source="vertex-qdrant-v3",
        )
        return evidence, candidate

    async def retrieve_detailed(
        self,
        dense_query: str,
        *,
        sparse_query: str,
        limit: int,
        fusion: str = "rrf",
    ) -> RetrievalOutcome:
        started = time.perf_counter()
        trace = RetrievalStageTrace()
        try:
            points = await query_vertex_points(
                dense_query,
                sparse_query=sparse_query,
                provider=self.provider,
                client=self.client,
                sparse_encoder=self.sparse_encoder,
                contract=self.contract,
                limit=limit,
                fusion=fusion,
            )
            converted = [self._evidence(point) for point in points]
        except Exception as error:
            latency = time.perf_counter() - started
            return RetrievalOutcome(
                evidence=[],
                latency={"vertex_qdrant": latency},
                status="retrieval_error",
                diagnostics={
                    "stage_trace": trace,
                    "backend": "vertex-qdrant-v3",
                    "error_type": type(error).__name__,
                },
                error=f"{type(error).__name__}: {error}",
            )
        evidence = [item[0] for item in converted]
        candidates = [item[1] for item in converted]
        trace.structural_chunks_generated = candidates
        trace.final_evidence_chunks = candidates
        return RetrievalOutcome(
            evidence=evidence,
            latency={"vertex_qdrant": time.perf_counter() - started},
            status="ok" if evidence else "no_candidate",
            diagnostics={
                "stage_trace": trace,
                "backend": "vertex-qdrant-v3",
                "collection": self.contract.collection_name,
            },
        )
