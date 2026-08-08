from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal


class ArtifactCollisionError(FileExistsError):
    status = "artifact_collision"


def canonical_json_bytes(data: Any) -> bytes:
    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def write_immutable_json(
    path: Path,
    data: Any,
) -> Literal["created", "reused"]:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(data)
    try:
        file = target.open("xb")
    except FileExistsError:
        if target.read_bytes() == payload:
            return "reused"
        raise ArtifactCollisionError(
            "Canonical artifact already exists with different bytes: "
            f"{target}"
        )
    try:
        with file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return "created"
