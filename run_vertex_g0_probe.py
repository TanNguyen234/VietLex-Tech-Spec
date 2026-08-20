from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from google.genai import types

from app.config import get_settings
from app.evaluation.artifact_io import canonical_json_bytes, write_immutable_json
from app.evaluation.provenance import collect_git_provenance
from app.evaluation.run_manifest import generate_unique_run_id, prepare_run_directory
from app.evaluation.vertex_g0_probe import PROBE_DIMENSIONS, run_dimension_probe
from app.services.vertex_ai import VertexAIError, get_vertex_provider


async def _run(output_root: Path) -> Path:
    settings = get_settings()
    provider = get_vertex_provider()
    generation = await provider.generate(
        "Trả lời đúng một từ: OK",
        max_output_tokens=64,
        thinking_level=types.ThinkingLevel.MINIMAL,
    )
    embedding = await provider.embed_query(
        "quy định thuế",
        output_dimensionality=384,
    )
    probe = await run_dimension_probe(
        provider,
        query="Điều kiện khấu trừ thuế thu nhập cá nhân là gì?",
        document=(
            "Cá nhân được khấu trừ thuế thu nhập cá nhân theo điều kiện "
            "do pháp luật quy định."
        ),
        document_title="Quy định khấu trừ thuế",
    )
    config = {
        "provider": "google_vertex_ai",
        "llm_model": settings.VERTEX_LLM_MODEL,
        "embedding_model": settings.VERTEX_EMBEDDING_MODEL,
        "project": settings.GOOGLE_CLOUD_PROJECT,
        "location": settings.GOOGLE_CLOUD_LOCATION,
        "request_timeout_seconds": settings.VERTEX_REQUEST_TIMEOUT_SECONDS,
        "max_retries": settings.VERTEX_MAX_RETRIES,
        "generation_thinking_level": "MINIMAL",
        "probe_dimensions": list(PROBE_DIMENSIONS),
        "auth": "application_default_credentials",
        "credential_material_persisted": False,
        "vector_write_enabled": False,
    }
    fingerprint = hashlib.sha256(canonical_json_bytes(config)).hexdigest()
    run_id = generate_unique_run_id("vertex-g0", fingerprint)
    run_dir = prepare_run_directory(output_root, run_id)
    provenance = collect_git_provenance()
    raw_results = {
        "preflight": {
            "status": "pass",
            "generation": generation.metadata.to_dict(),
            "embedding": {
                **embedding.metadata.to_dict(),
                "dimension": len(embedding.values),
                "l2_norm": embedding.l2_norm,
            },
        },
        "dimension_probe": probe,
    }
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G0",
        "command": "python run_vertex_g0_probe.py",
        "configuration_fingerprint": fingerprint,
        "git": provenance.model_dump(mode="json"),
        "dataset_revision": settings.DATASET_REVISION,
        "provider": "google_vertex_ai",
        "provider_models": [
            settings.VERTEX_LLM_MODEL,
            settings.VERTEX_EMBEDDING_MODEL,
        ],
        "status": "pass" if probe["status"] == "pass" else "fail",
        "remote_effects": {
            "generation_requests": 1,
            "embedding_requests": 13,
            "vector_database_writes": 0,
        },
    }
    write_immutable_json(run_dir / "configuration.json", config)
    write_immutable_json(run_dir / "raw_results.json", raw_results)
    write_immutable_json(run_dir / "manifest.json", manifest)
    report = (
        f"# Vertex AI G0 probe — {run_id}\n\n"
        f"- Status: `{manifest['status']}`\n"
        f"- Provider: `google_vertex_ai`\n"
        f"- LLM: `{settings.VERTEX_LLM_MODEL}`\n"
        f"- Embedding: `{settings.VERTEX_EMBEDDING_MODEL}`\n"
        f"- Dimensions: `{', '.join(map(str, PROBE_DIMENSIONS))}`\n"
        f"- Production vector writes: `0`\n"
        f"- Production retrieval changed: `false`\n"
        f"- Credential material persisted: `false`\n"
    )
    with (run_dir / "report.md").open("x", encoding="utf-8") as file:
        file.write(report)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the isolated Vertex AI G0 preflight and dimension probe."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("docs/evaluation/runs"),
    )
    args = parser.parse_args()
    try:
        run_dir = asyncio.run(_run(args.output_root))
    except VertexAIError as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": error.__class__.__name__,
                    "error_kind": error.kind,
                    "status_code": error.status_code,
                    "message": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 2
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    raw = json.loads((run_dir / "raw_results.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "run_dir": str(run_dir),
                "llm_latency_ms": raw["preflight"]["generation"]["latency_ms"],
                "embedding_latency_ms": raw["preflight"]["embedding"]["latency_ms"],
                "dimensions": list(PROBE_DIMENSIONS),
                "vector_database_writes": 0,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
