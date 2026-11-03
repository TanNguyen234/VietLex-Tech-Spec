from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Mapping, Sequence
from urllib.parse import urlparse
from app.services.official_search_plan import DOCUMENT_REFERENCE


_DOCUMENT_NUMBER = DOCUMENT_REFERENCE
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_PDF_PAGE_SCOPE = re.compile(r"^(\d+)-(\d+)/(\d+)$")
_SAFE_READ_METHOD = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_TRUSTED_CONTEXT_KIND = "trusted_official_evidence_v1"
_PUBLIC_SNAPSHOT_KIND = "owner_public_official_snapshot_v1"
_PROVENANCE_FIELDS = (
    "issuing_authority",
    "source_type",
    "legal_effect_status",
    "source_url",
    "source_sha256",
    "retrieved_at",
    "read_method",
    "document_sha256",
    "attachment_url",
    "page_start",
    "page_end",
    "page_count",
    "truncated",
    "snapshot_sha256",
)


class TrustedOfficialEvidenceContext(str):
    """Evidence from the validated official-source reader path."""


class EphemeralOfficialEvidenceContext(TrustedOfficialEvidenceContext):
    """Web evidence excluded from shared caches; validated owner snapshots may persist."""


@dataclass(frozen=True)
class EvidenceView:
    original: str
    document_id: int | None
    citation: str | None
    document_number: str | None
    title: str | None
    source_url: str | None
    excerpt: str
    source_type: str | None = None
    legal_effect_status: str | None = None
    source_sha256: str | None = None
    retrieved_at: str | None = None
    read_method: str | None = None
    document_sha256: str | None = None
    attachment_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    page_count: int | None = None
    truncated: bool | None = None
    issuing_authority: str | None = None


def _safe_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _approved_official_url(value: str) -> str | None:
    try:
        from app.services.trusted_source_reader import validate_source_url

        return validate_source_url(value)
    except (ImportError, TypeError, ValueError):
        return None


def present_context(text: str) -> EvidenceView:
    external_context = isinstance(text, TrustedOfficialEvidenceContext)
    original = str(text)
    lines = original.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    citation: str | None = None
    document_id: int | None = None
    title: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    legal_effect_status: str | None = None
    source_sha256: str | None = None
    retrieved_at: str | None = None
    read_method: str | None = None
    document_sha256: str | None = None
    attachment_url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    page_count: int | None = None
    truncated: bool | None = None
    issuing_authority: str | None = None
    excerpt_lines: list[str] = []
    metadata_section = True

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if external_context and not metadata_section:
            excerpt_lines.append(raw_line.strip())
            continue
        if citation is None and line.startswith("[") and line.endswith("]"):
            citation = line[1:-1].strip() or None
            continue
        if line.casefold().startswith("dẫn chiếu:"):
            citation = line.split(":", 1)[1].strip() or citation
            continue
        if line.casefold().startswith("id tài liệu:"):
            raw_id = line.split(":", 1)[1].strip()
            if raw_id.isdecimal() and int(raw_id) > 0:
                document_id = int(raw_id)
            continue
        if line.casefold().startswith("nguồn:"):
            value = line.split(":", 1)[1].strip()
            source_url = (
                _approved_official_url(value)
                if external_context
                else _safe_url(value)
            )
            continue
        if line.casefold().startswith("url:"):
            value = line.split(":", 1)[1].strip()
            source_url = (
                _approved_official_url(value)
                if external_context
                else _safe_url(value)
            )
            continue
        if line.casefold().startswith("tiêu đề:"):
            title = line.split(":", 1)[1].strip() or None
            if external_context:
                metadata_section = False
            continue
        if line.casefold().startswith("nguồn loại:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                source_type = value if value == "official_external" else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if external_context and line.casefold().startswith("cơ quan ban hành:"):
            issuing_authority = line.split(":", 1)[1].strip()[:200] or None
            continue
        if line.casefold().startswith("hiệu lực pháp lý:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                legal_effect_status = value if value in {"unverified", "conflicting"} else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        folded_line = line.casefold()
        if folded_line.startswith(("sha-256 nguồn:", "sha-256 nội dung trích xuất:")):
            if external_context:
                value = line.split(":", 1)[1].strip()
                source_sha256 = value.lower() if _SHA256.fullmatch(value) else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if folded_line.startswith("sha-256 tệp pdf:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                document_sha256 = value.lower() if _SHA256.fullmatch(value) else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if folded_line.startswith("tệp pdf:"):
            if external_context:
                attachment_url = _approved_official_url(
                    line.split(":", 1)[1].strip()
                )
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if folded_line.startswith("phạm vi trang pdf:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                match = _PDF_PAGE_SCOPE.fullmatch(value)
                if match:
                    start, end, count = map(int, match.groups())
                    if 1 <= start <= end <= count <= 200:
                        page_start, page_end, page_count = start, end, count
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if folded_line.startswith("đọc một phần pdf:"):
            if external_context:
                value = line.split(":", 1)[1].strip().casefold()
                truncated = {"có": True, "không": False}.get(value)
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if line.casefold().startswith("thời điểm đọc:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                retrieved_at = value[:64] if value and len(value) <= 64 else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if line.casefold().startswith("phương thức đọc:"):
            if external_context:
                value = line.split(":", 1)[1].strip()
                read_method = value[:80] if value and len(value) <= 80 else None
            else:
                excerpt_lines.append(raw_line.strip())
            continue
        if external_context:
            metadata_section = False
        excerpt_lines.append(raw_line.strip())

    document_match = _DOCUMENT_NUMBER.search(citation or original)
    return EvidenceView(
        original=original,
        document_id=document_id,
        citation=citation,
        document_number=(document_match.group().upper() if document_match else None),
        title=title,
        source_url=source_url,
        excerpt="\n".join(excerpt_lines).strip(),
        source_type=source_type,
        legal_effect_status=legal_effect_status,
        source_sha256=source_sha256,
        retrieved_at=retrieved_at,
        read_method=read_method,
        document_sha256=document_sha256,
        attachment_url=attachment_url,
        page_start=page_start,
        page_end=page_end,
        page_count=page_count,
        truncated=truncated,
        issuing_authority=issuing_authority,
    )


def _official_context_provenance(
    context: TrustedOfficialEvidenceContext,
) -> dict[str, object] | None:
    view = present_context(context)
    if (
        view.source_type != "official_external"
        or view.legal_effect_status not in {"unverified", "conflicting"}
        or not view.source_url
        or _approved_official_url(view.source_url) != view.source_url
        or not view.source_sha256
        or not view.retrieved_at
        or not view.read_method
        or not _SAFE_READ_METHOD.fullmatch(view.read_method)
    ):
        return None
    try:
        datetime.fromisoformat(view.retrieved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    provenance = {
        "source_type": view.source_type,
        "legal_effect_status": view.legal_effect_status,
        "source_url": view.source_url,
        "source_sha256": view.source_sha256,
        "retrieved_at": view.retrieved_at,
        "read_method": view.read_method,
    }
    if view.issuing_authority is not None:
        provenance["issuing_authority"] = view.issuing_authority
    pdf_values = (
        view.document_sha256,
        view.attachment_url,
        view.page_start,
        view.page_end,
        view.page_count,
        view.truncated,
    )
    if any(value is not None for value in pdf_values):
        if (
            not view.document_sha256
            or not _SHA256.fullmatch(view.document_sha256)
            or not view.attachment_url
            or _approved_official_url(view.attachment_url) != view.attachment_url
            or any(
                not isinstance(page, int) or isinstance(page, bool)
                for page in (view.page_start, view.page_end, view.page_count)
            )
            or not 1 <= view.page_start <= view.page_end <= view.page_count <= 200
            or not isinstance(view.truncated, bool)
            or view.truncated != (view.page_start > 1 or view.page_end < view.page_count)
        ):
            return None
        provenance.update(
            {
                "document_sha256": view.document_sha256,
                "attachment_url": view.attachment_url,
                "page_start": view.page_start,
                "page_end": view.page_end,
                "page_count": view.page_count,
                "truncated": view.truncated,
            }
        )
    return provenance


def serialize_evidence_context(context: str) -> str | dict[str, object]:
    """Keep the trusted marker only when the source value is the trusted type."""
    if not isinstance(context, TrustedOfficialEvidenceContext):
        return str(context)
    provenance = _official_context_provenance(context)
    if provenance is None:
        return str(context)
    ephemeral = isinstance(context, EphemeralOfficialEvidenceContext)
    if ephemeral:
        # Bind the exact retained excerpt as well as the reader's source hash.
        provenance["snapshot_sha256"] = hashlib.sha256(str(context).encode("utf-8")).hexdigest()
    return {
        "kind": _PUBLIC_SNAPSHOT_KIND if ephemeral else _TRUSTED_CONTEXT_KIND,
        "text": str(context),
        "provenance": provenance,
    }


def deserialize_evidence_context(value: object) -> str | TrustedOfficialEvidenceContext | None:
    """Restore trusted contexts while accepting legacy plain-string cache entries."""
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in {_TRUSTED_CONTEXT_KIND, _PUBLIC_SNAPSHOT_KIND}:
        return None
    text = value.get("text")
    provenance = value.get("provenance")
    if not isinstance(text, str) or not isinstance(provenance, Mapping):
        return None
    context = (EphemeralOfficialEvidenceContext(text) if kind == _PUBLIC_SNAPSHOT_KIND
               else TrustedOfficialEvidenceContext(text))
    expected = _official_context_provenance(context)
    if expected is None:
        return None
    if kind == _PUBLIC_SNAPSHOT_KIND:
        expected["snapshot_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if dict(provenance) != expected:
        return None
    return context


def evidence_context_provenance(context: str) -> dict[str, object] | None:
    """Return a Mongo-safe sidecar for a trusted context, or None for plain text."""
    encoded = serialize_evidence_context(context)
    if not isinstance(encoded, dict):
        return None
    return {"kind": encoded["kind"], **encoded["provenance"]}


def restore_evidence_contexts(
    contexts: Sequence[object], provenance: object
) -> list[object]:
    """Rehydrate a DB history sidecar; legacy rows remain plain strings."""
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
        return list(contexts)
    restored: list[object] = []
    for index, context in enumerate(contexts):
        sidecar = provenance[index] if index < len(provenance) else None
        if isinstance(context, str) and isinstance(sidecar, Mapping):
            structured_provenance = {
                key: sidecar[key]
                for key in _PROVENANCE_FIELDS
                if key in sidecar
            }
            restored_context = deserialize_evidence_context(
                {
                    "kind": sidecar.get("kind"),
                    "text": context,
                    "provenance": structured_provenance,
                }
            )
            if restored_context is not None:
                restored.append(restored_context)
                continue
        restored.append(context)
    return restored
