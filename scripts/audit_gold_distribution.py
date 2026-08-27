from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from app.config import get_settings
from app.evaluation.gold_sidecar import load_gold_sidecar
from app.evaluation.schemas import EvidenceStatus, GoldEvidence
from app.ingestion.content_store import ContentStore


def audit_gold_distribution(
    labels: Sequence[GoldEvidence],
    *,
    legal_types: Mapping[int, str] | None = None,
) -> dict[str, object]:
    verified = [item for item in labels if item.status == EvidenceStatus.VERIFIED]
    documents = [int(item.document_id) for item in verified if item.document_id is not None]
    document_counts = Counter(documents)
    levels = Counter(item.required_level.value for item in verified)
    case_count = len({item.case_id for item in verified})
    type_values = {
        legal_types[document_id]
        for document_id in set(documents)
        if legal_types and document_id in legal_types and legal_types[document_id]
    }
    denominator = len(labels)
    return {
        "verified_evidence": {
            "numerator": len(verified),
            "denominator": denominator,
            "coverage": len(verified) / denominator if denominator else None,
            "skipped": denominator - len(verified),
            "skip_reason": "status_not_verified",
        },
        "verified_cases": case_count,
        "distinct_documents": len(set(documents)),
        "distinct_legal_types": len(type_values),
        "legal_types": sorted(type_values),
        "level_counts": dict(sorted(levels.items())),
        "max_document_evidence_share": (
            max(document_counts.values()) / len(verified)
            if verified and document_counts
            else None
        ),
        "top_documents": [
            {"document_id": document_id, "evidence_count": count}
            for document_id, count in document_counts.most_common(10)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    sidecar = load_gold_sidecar(args.sidecar)
    settings = get_settings()
    store = ContentStore(settings.CONTENT_STORE_PATH)
    document_ids = {
        int(item.document_id)
        for item in sidecar.labels
        if item.status == EvidenceStatus.VERIFIED and item.document_id is not None
    }
    documents = store.get_many(sorted(document_ids))
    legal_types = {
        document_id: document.metadata.legal_type
        for document_id, document in documents.items()
    }
    print(
        json.dumps(
            audit_gold_distribution(sidecar.labels, legal_types=legal_types),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
