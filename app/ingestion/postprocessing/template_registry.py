import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ingestion.schemas import LegalDocumentSchema, TemplateRegistryEntry


class TemplateRegistry:
    """Small local registry for known HTML/source templates.

    Registry entries intentionally describe ownership and versioned support, not
    extraction selectors. Extractor-specific selectors belong in extractor code
    after a template is promoted to SUPPORTED by reviewed fixtures.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        self.registry_path = registry_path or Path(__file__).with_name("template_registry.json")
        self.entries = self._load_entries()

    def resolve(self, doc: LegalDocumentSchema) -> TemplateRegistryEntry:
        html = doc.html_text or ""
        source_key = self._source_key(doc)
        source_matches = [
            entry
            for entry in self.entries
            if self._entry_matches_source(entry, source_key)
        ]

        for entry in source_matches:
            if self._entry_matches_fingerprint(entry, html):
                return entry

        if source_matches:
            generic = next((entry for entry in source_matches if not entry.fingerprints), source_matches[0])
            if not generic.fingerprints:
                return generic

        if not html.strip():
            return TemplateRegistryEntry(
                source=doc.source or "unknown",
                template_id="legacy_plain_text",
                extractor="plain_text",
                owner="ingestion",
                supported_version="1",
                status="SUPPORTED",
                notes="Plain-text-only legacy input; no HTML template required.",
            )

        return TemplateRegistryEntry(
            source=doc.source or "unknown",
            template_id=f"{self._slug(source_key)}:unknown",
            extractor="generic",
            owner="unknown",
            supported_version="0",
            status="UNKNOWN",
            notes="No registry entry matched this source/template fingerprint.",
        )

    def compatibility_matrix(self) -> List[Dict[str, Any]]:
        return [
            {"module": "Metadata", "legacy": True, "verified": True, "migration_status": "Dual path"},
            {"module": "Parser", "legacy": True, "verified": False, "migration_status": "Resolver/AST gate in progress"},
            {"module": "Chunk", "legacy": True, "verified": False, "migration_status": "Deterministic chunks in progress"},
            {"module": "Validator", "legacy": False, "verified": True, "migration_status": "Verified-only gate"},
            {"module": "Index handoff", "legacy": True, "verified": False, "migration_status": "Preflight/audit handoff in progress"},
        ]

    def _load_entries(self) -> List[TemplateRegistryEntry]:
        if not self.registry_path.exists():
            return []

        with self.registry_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)

        return [TemplateRegistryEntry(**item) for item in payload.get("entries", [])]

    def _source_key(self, doc: LegalDocumentSchema) -> str:
        return " ".join([doc.source or "", doc.url or ""]).lower()

    def _entry_matches_source(self, entry: TemplateRegistryEntry, source_key: str) -> bool:
        return bool(entry.source and entry.source.lower() in source_key)

    def _entry_matches_fingerprint(self, entry: TemplateRegistryEntry, html: str) -> bool:
        if not entry.fingerprints:
            return False

        for pattern in entry.fingerprints:
            try:
                if re.search(pattern, html, re.IGNORECASE | re.DOTALL):
                    return True
            except re.error:
                if pattern.lower() in html.lower():
                    return True
        return False

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "unknown"
