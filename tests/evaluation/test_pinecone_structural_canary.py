from types import SimpleNamespace

from app.evaluation.pinecone_structural_canary import evaluate_pinecone_canaries
from app.evaluation.structural_model_probe import StructuralCanary
from app.ingestion.structural_pinecone import PineconeStructuralContract


def _canary(query_id: str, document_id: int) -> StructuralCanary:
    return StructuralCanary(
        query_id=query_id,
        query=f"Tiêu đề văn bản {document_id}",
        document_id=document_id,
        legal_type="Luật",
    )


def test_canary_evaluation_reports_exact_denominator_and_provider_usage() -> None:
    class Index:
        def search(self, **kwargs):
            target = int(kwargs["inputs"]["text"].rsplit(" ", 1)[-1])
            hits = [
                SimpleNamespace(fields={"document_id": target + 100}),
                SimpleNamespace(fields={"document_id": target}),
            ]
            return SimpleNamespace(
                result=SimpleNamespace(hits=hits),
                usage=SimpleNamespace(embed_total_tokens=5, read_units=1),
            )

    report = evaluate_pinecone_canaries(
        Index(),
        [_canary("canary-a", 1), _canary("canary-b", 2)],
        contract=PineconeStructuralContract(),
        dataset_sha256="a" * 64,
        sidecar_sha256="b" * 64,
        plan_sha256="c" * 64,
        upload_report_sha256="d" * 64,
        verify_report_sha256="e" * 64,
        source_state_sha256="f" * 64,
    )

    assert report.status == "PASS_CANARY"
    assert report.metrics["document_recall_at_10"].numerator == 2
    assert report.metrics["document_recall_at_10"].denominator == 2
    assert report.per_canary_first_relevant_rank == {
        "canary-a": 2,
        "canary-b": 2,
    }
    assert report.provider_usage == {
        "llama-text-embed-v2": 10,
        "pinecone_read_units": 2,
    }
    assert report.provider_calls == 2


def test_canary_evaluation_is_blocked_on_malformed_provider_result() -> None:
    class Index:
        def search(self, **_kwargs):
            return SimpleNamespace(
                result=SimpleNamespace(hits=[]),
                usage=SimpleNamespace(embed_total_tokens=None, read_units=1),
            )

    report = evaluate_pinecone_canaries(
        Index(),
        [_canary("canary-a", 1)],
        contract=PineconeStructuralContract(),
        dataset_sha256="a" * 64,
        sidecar_sha256="b" * 64,
        plan_sha256="c" * 64,
        upload_report_sha256="d" * 64,
        verify_report_sha256="e" * 64,
        source_state_sha256="f" * 64,
    )

    assert report.status == "BLOCKED_TECHNICAL"
    assert report.technical_errors == {"canary-a": "malformed_usage"}
    assert report.metrics["document_recall_at_10"].denominator == 0
