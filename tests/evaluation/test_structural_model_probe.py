from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from qdrant_client import models

from app.config import Settings
from app.evaluation.schemas import GoldEvidence, GoldenCase
from app.evaluation.structural_model_probe import (
    PineconeReferenceEmbedder,
    PineconeReferenceResult,
    ProbeMetric,
    StructuralModelProbeInput,
    StructuralProbeSelection,
    load_verified_probe_scope,
    run_structural_model_probe,
    decide_model_probe_acceptance,
    select_model_probe_records,
)
from app.ingestion.content_store import StoredDocument
from app.ingestion.legal_text import DocumentMetadata
from app.ingestion.structural_index import (
    StructuralRecord,
    build_structural_records,
)
from app.ingestion.structural_pilot import (
    CapacityEnvelope,
    CollectionCreationReceipt,
    CollectionSchemaReceipt,
    build_structural_pilot_plan,
)
from app.ingestion.structural_qdrant import InferenceUsageReceipt


def _record(
    record_id: str,
    document_id: int,
    *,
    article: str | None = "Điều 1",
    clause: str | None = None,
    body: str | None = None,
) -> StructuralRecord:
    text = body or f"{article or 'Văn bản'} nội dung {record_id}"
    return StructuralRecord(
        record_id=record_id,
        body=text,
        document_id=document_id,
        document_number=f"{document_id}/2026/QH15",
        title=f"Luật {document_id}",
        source_url=f"https://example.invalid/{document_id}",
        legal_type="Luật",
        issuing_authority="Quốc hội",
        issuance_date="01/01/2026",
        article=article,
        clause=clause,
        heading_path=article or "Văn bản",
        citation=f"{document_id}/2026/QH15, {article or 'Văn bản'}",
        token_count=max(1, len(text.split())),
        dataset_revision="revision-1",
        content_sha256=hashlib.sha256(
            f"document-{document_id}".encode()
        ).hexdigest(),
        chunk_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def _case(
    case_id: str,
    document_id: int,
    *,
    article: str | None = "Điều 1",
    clause: str | None = None,
    required_level: str = "article",
    status: str = "verified",
) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        question=f"Question {case_id}",
        question_type="factoid",
        answerable=True,
        reference_answer="Answer",
        gold_evidence=[
            GoldEvidence(
                evidence_item_id=f"{case_id}-e1",
                case_id=case_id,
                document_id=document_id,
                document_number=f"{document_id}/2026/QH15",
                article=article,
                clause=clause,
                required=True,
                required_level=required_level,
                status=status,
            )
        ],
    )


def test_probe_selection_uses_only_verified_required_in_scope_records() -> None:
    records = [
        _record("00000000-0000-0000-0000-000000000001", 1),
        _record("00000000-0000-0000-0000-000000000002", 1, article="Điều 2"),
        _record(
            "00000000-0000-0000-0000-000000000003",
            2,
            clause="1",
        ),
    ]
    cases = [
        _case("case-001", 1),
        _case("case-002", 2, clause="1", required_level="clause"),
        _case("case-003", 3),
    ]

    selection = select_model_probe_records(cases, iter(records))

    assert selection.case_ids == ("case-001", "case-002")
    assert selection.record_ids == (
        records[0].record_id,
        records[2].record_id,
    )
    assert selection.synthetic_records == 0
    assert selection.skipped_cases == {
        "case-003": "outside_primary_legislation_scope"
    }


def test_probe_selection_includes_one_real_negative_per_non_gold_document() -> None:
    records = [
        _record("00000000-0000-0000-0000-000000000001", 1),
        _record("00000000-0000-0000-0000-000000000002", 2),
        _record("00000000-0000-0000-0000-000000000003", 3),
        _record(
            "00000000-0000-0000-0000-000000000004",
            3,
            article="Điều 2",
        ),
        _record("00000000-0000-0000-0000-000000000005", 4),
    ]

    selection = select_model_probe_records(
        [_case("case-001", 1), _case("case-002", 2)],
        records,
    )

    assert {record.document_id for record in selection.records} == {1, 2, 3, 4}
    assert set(selection.relevant_record_ids) == {
        records[0].record_id,
        records[1].record_id,
    }
    assert len(selection.hard_negative_record_ids) == 2
    assert set(selection.hard_negative_record_ids).issubset(selection.record_ids)
    assert selection.synthetic_records == 0


def test_probe_distractor_and_canary_selection_is_iteration_order_stable() -> None:
    records = [
        _record(f"00000000-0000-0000-0000-{index:012d}", index)
        for index in range(1, 70)
    ]
    cases = [_case("case-001", 1)]

    forward = select_model_probe_records(cases, records)
    reverse = select_model_probe_records(cases, reversed(records))

    assert forward.record_ids == reverse.record_ids
    assert forward.hard_negative_record_ids == reverse.hard_negative_record_ids
    assert forward.canary_queries == reverse.canary_queries
    assert len(forward.canary_queries) == 64
    assert all(canary.document_id != 1 for canary in forward.canary_queries)


def test_probe_selection_reports_verified_structure_not_resolved() -> None:
    selection = select_model_probe_records(
        [_case("case-001", 1, article="Điều 99")],
        iter([_record("00000000-0000-0000-0000-000000000001", 1)]),
    )

    assert selection.case_ids == ()
    assert selection.record_ids == ()
    assert selection.skipped_cases == {
        "case-001": "verified_structure_not_resolved"
    }


def test_scope_loader_binds_exact_dataset_and_sidecar_bytes(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "question": "Question case_001",
                    "question_type": "factoid",
                    "ground_truth_answer": "Answer",
                    "ground_truth_context": ["Context"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sidecar = tmp_path / "labels.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "dataset_name": "fixture",
                "total_cases": 1,
                "total_evidence_items": 1,
                "labels": [
                    {
                        "evidence_item_id": "case_001-e1",
                        "case_id": "case_001",
                        "document_id": 1,
                        "document_number": "1/2026/QH15",
                        "article": "Điều 1",
                        "required": True,
                        "required_level": "article",
                        "status": "verified",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    record = _record("00000000-0000-0000-0000-000000000001", 1)

    scope = load_verified_probe_scope(dataset, sidecar, iter([record]))

    assert scope.dataset_sha256 == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert scope.sidecar_sha256 == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    assert scope.selection.case_ids == ("case_001",)
    assert scope.selection.record_ids == (record.record_id,)

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["labels"][0]["case_id"] = "case_extra"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Case ID set mismatch"):
        load_verified_probe_scope(dataset, sidecar, iter([record]))


class _Store:
    def __init__(self) -> None:
        self.documents = {
            document_id: self._document(document_id)
            for document_id in range(1, 5)
        }

    @staticmethod
    def _document(document_id: int) -> StoredDocument:
        body = f"Điều 1. Quy định cho document {document_id}."
        return StoredDocument(
            metadata=DocumentMetadata(
                document_id=document_id,
                document_number=f"{document_id}/2026/QH15",
                title=f"Luật {document_id}",
                source_url=f"https://example.invalid/{document_id}",
                legal_type="Luật",
                legal_sectors="Khác",
                issuing_authority="Quốc hội",
                issuance_date="01/01/2026",
            ),
            content=body,
            content_sha256=hashlib.sha256(body.encode()).hexdigest(),
            content_store_key=str(document_id),
            quality_flags=(),
        )

    def iter_document_ids_by_legal_types(
        self, legal_types, *, after_id: int, limit: int
    ) -> list[int]:
        return [
            value for value in range(1, 5) if value > after_id
        ][:limit]

    def get_many(self, ids: list[int]) -> dict[int, StoredDocument]:
        return {value: self.documents[value] for value in ids}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        DATASET_REPOSITORY="owner/legal-corpus",
        DATASET_REVISION="revision-1",
    )


def _provenance():
    from app.evaluation.provenance import GitProvenance

    return GitProvenance(
        status="ok",
        repository_root="D:/repo",
        git_sha="a" * 40,
        git_dirty=False,
        git_tracked_dirty=False,
        git_staged_dirty=False,
        git_untracked_dirty=False,
        git_diff_sha256=None,
        git_diff_status="clean",
        source_state_sha256="b" * 64,
    )


def _probe_input(tmp_path: Path) -> StructuralModelProbeInput:
    settings = _settings()
    store = _Store()
    plan = build_structural_pilot_plan(
        store=store,
        settings=settings,
        output_root=tmp_path,
        capacity=CapacityEnvelope(
            disk_bytes=1024**3,
            ram_bytes=1024**3,
            vcpu=1,
            existing_disk_bytes=0,
            shard_count=1,
        ),
        provenance=_provenance(),
        run_id="probe-plan",
    )
    records = build_structural_records(
        store,
        [1, 2, 3, 4],
        repository=settings.DATASET_REPOSITORY,
        revision=settings.DATASET_REVISION,
    )
    cases = [_case("case-001", 1), _case("case-002", 2)]
    selection = select_model_probe_records(cases, iter(records))
    receipt = CollectionCreationReceipt(
        status="ADOPTED_EMPTY",
        collection_name="vietlex-legal-rag-v2-pilot-384",
        started_at_utc="2026-08-10T00:00:00Z",
        verified_at_utc="2026-08-10T00:00:01Z",
        source_state_sha256=plan.source_state_sha256,
        plan_sha256=plan.plan_sha256,
        schema_readback=CollectionSchemaReceipt(
            dense_vector_name="dense",
            dense_size=384,
            dense_distance="Cosine",
            dense_on_disk=True,
            sparse_vector_name="bm25",
            sparse_modifier="idf",
            sparse_on_disk=True,
            hnsw_m=0,
            hnsw_on_disk=True,
            shard_number=1,
            on_disk_payload=True,
        ),
        payload_indexes=("dataset_revision", "document_id", "legal_type"),
        points_count=0,
        provider_calls=2,
        inference_calls=0,
    )
    return StructuralModelProbeInput(
        plan=plan,
        creation_receipt=receipt,
        creation_receipt_sha256="c" * 64,
        selection=selection,
        dataset_sha256="d" * 64,
        sidecar_sha256="e" * 64,
        output_path=tmp_path / plan.run_id / "model-probe.json",
    )


def _metric(value: float, denominator: int) -> ProbeMetric:
    return ProbeMetric(
        numerator=value * denominator,
        denominator=denominator,
        value=value,
    )


def test_probe_metric_rejects_inconsistent_or_fabricated_ratio() -> None:
    with pytest.raises(ValidationError, match="inconsistent"):
        ProbeMetric(numerator=1, denominator=2, value=1.0)


@pytest.mark.parametrize(
    ("document_recall", "structural_recall", "canary_recall", "expected"),
    [
        (1.0, 0.95, 0.90, "PASS_MODEL_PROBE"),
        (0.99, 0.95, 0.90, "FAIL_QUALITY"),
        (1.0, 0.949, 0.90, "FAIL_QUALITY"),
        (1.0, 0.95, 0.899, "FAIL_QUALITY"),
    ],
)
def test_model_probe_acceptance_uses_absolute_quality_gates(
    document_recall: float,
    structural_recall: float,
    canary_recall: float,
    expected: str,
) -> None:
    assert decide_model_probe_acceptance(
        gold_document_recall_at_10=document_recall,
        gold_structural_recall_at_10=structural_recall,
        canary_document_recall_at_10=canary_recall,
        technical_error_count=0,
    ) == expected


class FakeReference:
    def __init__(
        self,
        *,
        case_hash: str | None = None,
        usage: int = 100,
        metrics: dict[str, ProbeMetric] | None = None,
        wrong_usage_model: bool = False,
    ) -> None:
        self.case_hash = case_hash
        self.usage = usage
        self.metrics = metrics
        self.wrong_usage_model = wrong_usage_model

    def evaluate(self, probe: StructuralModelProbeInput) -> PineconeReferenceResult:
        denominator = len(probe.selection.cases)
        return PineconeReferenceResult(
            model="llama-text-embed-v2",
            dimension=1024,
            dataset_sha256=probe.dataset_sha256,
            sidecar_sha256=probe.sidecar_sha256,
            source_state_sha256=probe.plan.source_state_sha256,
            case_ids_sha256=self.case_hash or probe.selection.case_ids_sha256,
            record_ids_sha256=probe.selection.record_ids_sha256,
            text_sha256=probe.selection.text_sha256,
            metrics=self.metrics
            or {
                "recall_at_1": _metric(1.0, denominator),
                "recall_at_3": _metric(1.0, denominator),
                "mrr": _metric(1.0, denominator),
            },
            per_query_first_relevant_rank={
                case.case_id: 1 for case in probe.selection.cases
            },
            provider_usage={
                (
                    "wrong-reference-model"
                    if self.wrong_usage_model
                    else "llama-text-embed-v2"
                ): self.usage
            },
            passage_input_count=len(probe.selection.records),
            query_input_count=denominator,
            provider_calls=2,
        )


class FakeProbeClient:
    def __init__(self, *, vector_problem: str | None = None) -> None:
        self.points: dict[str, object] = {}
        self.vector_problem = vector_problem
        self.delete_calls: list[object] = []

    def get_collection(self, collection_name: str):
        return SimpleNamespace(
            points_count=len(self.points),
            payload_schema={
                "dataset_revision": SimpleNamespace(
                    data_type=models.PayloadSchemaType.KEYWORD
                ),
                "legal_type": SimpleNamespace(
                    data_type=models.PayloadSchemaType.KEYWORD
                ),
                "document_id": SimpleNamespace(
                    data_type=models.PayloadSchemaType.INTEGER
                ),
            },
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors={
                        "dense": models.VectorParams(
                            size=(
                                1024
                                if self.vector_problem == "schema"
                                else 384
                            ),
                            distance=models.Distance.COSINE,
                            on_disk=True,
                        )
                    },
                    sparse_vectors={
                        "bm25": models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=True),
                            modifier=models.Modifier.IDF,
                        )
                    },
                    shard_number=1,
                    on_disk_payload=True,
                ),
                hnsw_config=models.HnswConfigDiff(m=0, on_disk=True),
            ),
        )

    def retrieve(self, collection_name, ids, **kwargs):
        rows = []
        for point_id in ids:
            point = self.points[str(point_id)]
            dense = [0.0] * 384
            dense[0] = 1.0
            sparse_indices = [1]
            sparse_values = [1.0]
            if self.vector_problem == "dimension":
                dense.pop()
            elif self.vector_problem == "nonfinite":
                dense[0] = math.nan
            elif self.vector_problem == "sparse_empty":
                sparse_indices = []
                sparse_values = []
            rows.append(
                SimpleNamespace(
                    id=point.id,
                    payload=point.payload,
                    vector={
                        "dense": dense,
                        "bm25": models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                    },
                )
            )
        return rows


class FakeTransport:
    def __init__(
        self,
        probe: StructuralModelProbeInput,
        *,
        usage_problem: str | None = None,
        vector_problem: str | None = None,
        fail_query: bool = False,
        rank_problem: bool = False,
    ) -> None:
        self.contract = probe.plan.contract
        self.client = FakeProbeClient(vector_problem=vector_problem)
        self.usage_problem = usage_problem
        self.fail_query = fail_query
        self.rank_problem = rank_problem
        self.upsert_batches: list[list[object]] = []

    def upsert_with_usage(self, points):
        batch = list(points)
        self.upsert_batches.append(batch)
        self.client.points.update({str(point.id): point for point in batch})
        usage = {
            self.contract.dense_model: 100,
            self.contract.sparse_model: 100,
        }
        if self.usage_problem == "missing":
            usage.pop(self.contract.sparse_model)
        elif self.usage_problem == "wrong":
            usage = {"wrong-model": 100}
        return InferenceUsageReceipt(
            status="completed",
            elapsed_seconds=0.1,
            model_tokens=usage,
        )

    def query_with_usage(self, *, document, using, limit, **kwargs):
        if self.fail_query:
            raise RuntimeError("secret provider detail")
        if "case-" in document.text:
            case_id = document.text.rsplit("case-", 1)[-1]
            desired_document = 1 if case_id.startswith("001") else 2
        else:
            desired_document = int(document.text.rsplit("Luật ", 1)[-1])
        ordered = sorted(
            self.client.points.values(),
            key=lambda point: (
                point.payload["document_id"] != desired_document,
                str(point.id),
            ),
        )
        if self.rank_problem and desired_document == 1:
            ordered = [
                point
                for point in ordered
                if point.payload["document_id"] != desired_document
            ]
        hits = [
            SimpleNamespace(id=point.id, payload=point.payload, score=1.0)
            for point in ordered[:limit]
        ]
        return hits, InferenceUsageReceipt(
            status="completed",
            elapsed_seconds=0.01,
            model_tokens={self.contract.dense_model: 10},
        )


def test_probe_pass_requires_matched_denominator_and_provider_usage(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)
    transport = FakeTransport(probe)

    report = run_structural_model_probe(
        transport,
        probe,
        FakeReference(),
    )

    assert report.acceptance == "PASS_MODEL_PROBE"
    assert report.metrics["recall_at_1"].value == 1.0
    assert report.metrics["recall_at_3"].value == 1.0
    assert report.metrics["mrr"].value == 1.0
    assert report.reference is not None
    assert report.reference.case_ids_sha256 == report.case_ids_sha256
    assert report.provider_usage["intfloat/multilingual-e5-small"] > 0
    assert report.provider_usage["qdrant/bm25"] > 0
    assert report.provider_usage["llama-text-embed-v2"] > 0
    assert set(report.upsert_provider_usage) == {
        "intfloat/multilingual-e5-small",
        "qdrant/bm25",
    }
    assert set(report.query_provider_usage) == {
        "intfloat/multilingual-e5-small"
    }
    assert report.dataset_sha256 == "d" * 64
    assert report.sidecar_sha256 == "e" * 64
    assert report.synthetic_records == 0
    assert report.sampling_version == "primary-scope-hard-negatives-v1"
    assert report.relevant_record_ids == probe.selection.relevant_record_ids
    assert (
        report.hard_negative_record_ids
        == probe.selection.hard_negative_record_ids
    )
    assert report.canary_queries == probe.selection.canary_queries
    assert report.canary_skips == probe.selection.canary_skips
    assert set(report.probe_inference_text_hashes) == set(
        probe.selection.record_ids
    )
    assert all(
        len(value) == 64
        for value in report.probe_inference_text_hashes.values()
    )
    assert report.coverage.value == 1.0
    assert probe.output_path.is_file()
    assert [str(point.id) for point in transport.upsert_batches[0]] == list(
        probe.selection.record_ids
    )
    assert transport.client.delete_calls == []


def test_probe_passes_without_constructing_a_pinecone_reference(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)

    report = run_structural_model_probe(
        FakeTransport(probe),
        probe,
    )

    assert report.acceptance == "PASS_MODEL_PROBE"
    assert report.reference is None
    assert set(report.provider_usage) == {
        "intfloat/multilingual-e5-small",
        "qdrant/bm25",
    }


def test_probe_reports_canary_metrics_on_a_separate_denominator(
    tmp_path: Path,
) -> None:
    records = [
        _record(f"00000000-0000-0000-0000-{index:012d}", index)
        for index in range(1, 70)
    ]
    selection = select_model_probe_records(
        [_case("case-001", 1)],
        records,
    )
    probe = _probe_input(tmp_path).with_selection(selection)

    report = run_structural_model_probe(
        FakeTransport(probe),
        probe,
        FakeReference(),
    )

    assert report.metrics["recall_at_3"].denominator == 1
    assert report.canary_metrics["document_recall_at_10"].denominator == 64
    assert report.canary_metrics["document_recall_at_10"].value == 1.0
    assert set(report.per_canary_first_relevant_rank) == {
        canary.query_id for canary in selection.canary_queries
    }


def test_probe_valid_execution_below_floor_is_fail_quality(tmp_path: Path) -> None:
    probe = _probe_input(tmp_path)

    report = run_structural_model_probe(
        FakeTransport(probe, rank_problem=True),
        probe,
        FakeReference(),
    )

    assert report.acceptance == "FAIL_QUALITY"
    assert report.metrics["recall_at_1"].value == 0.5
    assert report.technical_errors == {}


def test_empty_verified_scope_is_blocked_with_zero_denominator(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)
    probe = probe.with_selection(
        StructuralProbeSelection.from_resolved(
            cases=(),
            records=(),
            skipped_cases={"case-001": "outside_primary_legislation_scope"},
        )
    )

    report = run_structural_model_probe(
        FakeTransport(probe),
        probe,
        FakeReference(),
    )

    assert report.acceptance == "BLOCKED_SCOPE"
    assert report.metrics["recall_at_1"].denominator == 0
    assert report.metrics["recall_at_1"].value is None


@pytest.mark.parametrize(
    ("reference", "usage_problem", "vector_problem", "fail_query"),
    [
        (FakeReference(case_hash="0" * 64), None, None, False),
        (FakeReference(usage=0), None, None, False),
        (FakeReference(wrong_usage_model=True), None, None, False),
        (FakeReference(), "missing", None, False),
        (FakeReference(), "wrong", None, False),
        (FakeReference(), None, "dimension", False),
        (FakeReference(), None, "nonfinite", False),
        (FakeReference(), None, "sparse_empty", False),
        (FakeReference(), None, "schema", False),
        (FakeReference(), None, None, True),
    ],
)
def test_probe_failures_are_typed_immutable_and_never_cleanup(
    tmp_path: Path,
    reference: FakeReference,
    usage_problem: str | None,
    vector_problem: str | None,
    fail_query: bool,
) -> None:
    probe = _probe_input(tmp_path)
    transport = FakeTransport(
        probe,
        usage_problem=usage_problem,
        vector_problem=vector_problem,
        fail_query=fail_query,
    )

    report = run_structural_model_probe(transport, probe, reference)

    assert report.acceptance == "BLOCKED_TECHNICAL"
    assert report.technical_errors
    assert probe.output_path.is_file()
    assert "secret provider detail" not in probe.output_path.read_text(
        encoding="utf-8"
    )
    assert transport.client.delete_calls == []


def test_reference_denominator_mismatch_blocks_before_qdrant_write(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)
    one_case_metrics = {
        "recall_at_1": _metric(1.0, 1),
        "recall_at_3": _metric(1.0, 1),
        "mrr": _metric(1.0, 1),
    }
    transport = FakeTransport(probe)

    report = run_structural_model_probe(
        transport,
        probe,
        FakeReference(metrics=one_case_metrics),
    )

    assert report.acceptance == "BLOCKED_TECHNICAL"
    assert transport.upsert_batches == []


def test_probe_batches_real_ids_at_sixty_four_without_synthetic_rows(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)
    base = probe.selection.records[0]
    records = tuple(
        base.model_copy(
            update={
                "record_id": f"00000000-0000-0000-0000-{index:012d}",
                "body": f"Điều 1 nội dung {index}",
                "chunk_sha256": hashlib.sha256(
                    f"Điều 1 nội dung {index}".encode()
                ).hexdigest(),
            }
        )
        for index in range(1, 66)
    )
    case = _case("case-001", base.document_id)
    selection = StructuralProbeSelection.from_resolved(
        cases=(case,),
        records=records,
        skipped_cases={},
    )
    probe = probe.with_selection(selection)
    transport = FakeTransport(probe)

    report = run_structural_model_probe(transport, probe, FakeReference())

    assert report.acceptance == "BLOCKED_SCOPE"
    assert [len(batch) for batch in transport.upsert_batches] == [64, 1]
    assert report.synthetic_records == 0


class FakeInference:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.index_calls = 0

    def embed(self, *, model, inputs, parameters):
        self.calls.append(
            {"model": model, "inputs": list(inputs), "parameters": parameters}
        )
        rows = []
        for index, _value in enumerate(inputs):
            vector = [0.0] * 1024
            vector[index % 2] = 1.0
            rows.append(SimpleNamespace(values=vector))
        return SimpleNamespace(
            model=model,
            data=rows,
            usage=SimpleNamespace(total_tokens=len(inputs) * 5),
        )

    def index(self, *_args, **_kwargs):
        self.index_calls += 1
        raise AssertionError("reference probe must not use Pinecone storage")


def test_pinecone_reference_embedder_uses_inference_only_and_exact_options(
    tmp_path: Path,
) -> None:
    probe = _probe_input(tmp_path)
    inference = FakeInference()

    reference = PineconeReferenceEmbedder(inference).evaluate(probe)

    assert reference.model == "llama-text-embed-v2"
    assert reference.dimension == 1024
    assert reference.case_ids_sha256 == probe.selection.case_ids_sha256
    assert inference.index_calls == 0
    assert {call["parameters"]["input_type"] for call in inference.calls} == {
        "passage",
        "query",
    }
    assert all(call["parameters"]["dimension"] == 1024 for call in inference.calls)
    assert all(len(call["inputs"]) <= 96 for call in inference.calls)
    assert reference.provider_usage["llama-text-embed-v2"] > 0
