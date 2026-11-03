from __future__ import annotations

import json
import sys
from io import BytesIO, TextIOWrapper
from types import SimpleNamespace

from app.evaluation.schemas import EvidenceStatus, GoldEvidence, RequiredLevel


def _label(case: str, document: int, level: RequiredLevel) -> GoldEvidence:
    return GoldEvidence(
        evidence_item_id=f"{case}-{document}-{level.value}",
        case_id=case,
        document_id=document,
        document_number=str(document),
        required=True,
        required_level=level,
        status=EvidenceStatus.VERIFIED,
    )


def test_gold_distribution_reports_concentration_and_coverage() -> None:
    from scripts.audit_gold_distribution import audit_gold_distribution

    report = audit_gold_distribution(
        [
            _label("case_1", 1, RequiredLevel.DOCUMENT),
            _label("case_2", 1, RequiredLevel.ARTICLE),
            _label("case_3", 2, RequiredLevel.CLAUSE),
        ],
        legal_types={1: "Luật", 2: "Nghị định"},
    )

    assert report["verified_evidence"]["numerator"] == 3
    assert report["distinct_documents"] == 2
    assert report["distinct_legal_types"] == 2
    assert report["level_counts"] == {"article": 1, "clause": 1, "document": 1}
    assert report["max_document_evidence_share"] == 2 / 3


def test_audit_gold_distribution_cli_is_safe_for_legacy_console_encoding(
    monkeypatch, tmp_path
) -> None:
    import scripts.audit_gold_distribution as cli

    output = BytesIO()
    console = TextIOWrapper(output, encoding="cp1252")
    labels = [_label("case_1", 1, RequiredLevel.DOCUMENT)]
    store = SimpleNamespace(
        get_many=lambda _ids: {
            1: SimpleNamespace(
                metadata=SimpleNamespace(legal_type="Pháp luật")
            )
        }
    )
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_gold_distribution.py", str(tmp_path / "labels.json")],
    )
    monkeypatch.setattr(
        cli, "load_gold_sidecar", lambda _path: SimpleNamespace(labels=labels)
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(CONTENT_STORE_PATH=tmp_path / "content.sqlite3"),
    )
    monkeypatch.setattr(cli, "ContentStore", lambda _path: store)

    assert cli.main() == 0
    console.flush()
    rendered = output.getvalue().decode("ascii")

    assert json.loads(rendered)["legal_types"] == ["Pháp luật"]
