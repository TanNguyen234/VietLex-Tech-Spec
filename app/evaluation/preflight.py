from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from app.evaluation.artifact_io import (
    ArtifactCollisionError,
    canonical_json_bytes,
    write_immutable_json,
)
from app.evaluation.case_selection import CaseSelectionResult
from app.evaluation.profiles import EvaluationProfile
from app.evaluation.provenance import GitProvenance
from app.evaluation.run_manifest import calculate_configuration_fingerprint


def build_preflight_batch(
    *,
    profiles: Sequence[EvaluationProfile],
    selection: CaseSelectionResult,
    provenance: GitProvenance,
    dataset_sha256: str,
    dataset_revision: str,
    sidecar_sha256: str,
    gold_policy: str,
    verified_only: bool,
    artifact_prefix: PurePosixPath,
) -> dict[str, Any]:
    provenance_blocked = (
        provenance.status != "ok"
        or provenance.source_state_sha256 is None
    )
    zero_selection_blocked = (
        verified_only and selection.selected_case_count == 0
    )
    blocked = provenance_blocked or zero_selection_blocked
    meta = {
        "git_sha": provenance.git_sha,
        "git_dirty": provenance.git_dirty,
        "git_diff_sha256": provenance.git_diff_sha256,
        "source_state_sha256": provenance.source_state_sha256,
        "provenance_status": provenance.status,
        "provenance_error": provenance.error,
        "git_diff_status": provenance.git_diff_status,
        "git_diff_reason": provenance.git_diff_reason,
        "dataset_revision": dataset_revision,
        "dataset_sha256": dataset_sha256,
        "sidecar_sha256": sidecar_sha256,
        "gold_policy": gold_policy,
        "verified_only": verified_only,
        "provider_calls": 0,
        "batch_status": "BLOCKED" if blocked else "OK",
        "status_code": "preflight_blocked" if blocked else "ok",
        "blocked_reason": (
            "provenance_unavailable"
            if provenance_blocked
            else "selected_case_count_is_zero_under_verified_only"
            if zero_selection_blocked
            else None
        ),
    }
    case_selection = {
        "selected_case_count": selection.selected_case_count,
        "selected_case_ids": selection.selected_case_ids,
        "selected_case_ids_sha256": selection.selected_case_ids_sha256,
    }
    profile_payloads: dict[str, Any] = {}
    for profile in profiles:
        if profile.name in profile_payloads:
            raise ValueError(f"duplicate preflight profile: {profile.name}")
        config = {
            "profile_name": profile.name,
            "profile": profile.to_dict(),
            "gold_policy": gold_policy,
            "verified_only": verified_only,
            "selected_case_ids_sha256": (
                selection.selected_case_ids_sha256
            ),
            "source_state_sha256": provenance.source_state_sha256,
        }
        fingerprint = calculate_configuration_fingerprint(config)
        filename = (
            f"preflight_{profile.name}_{fingerprint[:8]}_"
            f"{dataset_sha256[:8]}_{sidecar_sha256[:8]}_"
            f"{(provenance.source_state_sha256 or 'unknown')[:8]}.json"
        )
        profile_payloads[profile.name] = {
            "profile_name": profile.name,
            "profile": profile.to_dict(),
            "configuration_fingerprint": fingerprint,
            "selected_case_count": selection.selected_case_count,
            "selected_case_ids_sha256": (
                selection.selected_case_ids_sha256
            ),
            "source_state_sha256": provenance.source_state_sha256,
            "canonical_artifact_path": (
                artifact_prefix / filename
            ).as_posix(),
        }
    batch_configuration_fingerprint = (
        calculate_configuration_fingerprint(
            {
                "dataset_sha256": dataset_sha256,
                "sidecar_sha256": sidecar_sha256,
                "source_state_sha256": provenance.source_state_sha256,
                "selected_case_ids_sha256": (
                    selection.selected_case_ids_sha256
                ),
                "profiles": {
                    name: value["configuration_fingerprint"]
                    for name, value in profile_payloads.items()
                },
            }
        )
    )
    meta["batch_configuration_fingerprint"] = (
        batch_configuration_fingerprint
    )
    return {
        "schema_version": "3.0.0",
        "meta": meta,
        "case_selection": case_selection,
        "profiles": profile_payloads,
    }


def persist_preflight_batch(
    *,
    payload: dict[str, Any],
    output_dir: Path,
) -> list[tuple[Path, str]]:
    root = Path(output_dir).resolve()
    planned: list[tuple[Path, dict[str, Any]]] = []
    for profile in payload["profiles"].values():
        filename = PurePosixPath(
            profile["canonical_artifact_path"]
        ).name
        profile_payload = {
            "schema_version": payload["schema_version"],
            "meta": copy.deepcopy(payload["meta"]),
            "case_selection": copy.deepcopy(payload["case_selection"]),
            "profile": copy.deepcopy(profile),
        }
        planned.append((root / filename, profile_payload))

    comparison_name = (
        f"preflight_comparison_{payload['meta']['dataset_sha256'][:8]}_"
        f"{payload['meta']['sidecar_sha256'][:8]}_"
        f"{(payload['meta']['source_state_sha256'] or 'unknown')[:8]}_"
        f"{payload['meta']['batch_configuration_fingerprint'][:8]}.json"
    )
    planned.append((root / comparison_name, copy.deepcopy(payload)))

    canonical_payloads = [
        (target, artifact_payload, canonical_json_bytes(artifact_payload))
        for target, artifact_payload in planned
    ]
    for target, _, canonical_bytes in canonical_payloads:
        if target.exists() and target.read_bytes() != canonical_bytes:
            raise ArtifactCollisionError(
                "Canonical artifact already exists with different bytes: "
                f"{target}"
            )

    return [
        (target, write_immutable_json(target, artifact_payload))
        for target, artifact_payload, _ in canonical_payloads
    ]
