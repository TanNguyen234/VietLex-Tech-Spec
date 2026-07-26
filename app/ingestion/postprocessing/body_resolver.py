import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from app.ingestion.schemas import (
    BodyCandidate,
    BodyResolution,
    ConfidenceExplanation,
    EvidenceGraph,
    EvidenceNode,
    LegalDocumentSchema,
    ProcessingDisposition,
    TemplateRegistryEntry,
    TextBlock,
)
from app.ingestion.postprocessing.text_normalizer import TextNormalizer


class BodyResolver:
    """Resolve canonical body text from raw full_text/html_text with evidence."""

    def __init__(self, normalizer: Optional[TextNormalizer] = None):
        self.normalizer = normalizer or TextNormalizer()

    def resolve(self, doc: LegalDocumentSchema, template: TemplateRegistryEntry) -> BodyResolution:
        document_hash = self._document_hash(doc)
        candidates = self._build_candidates(doc)

        if not candidates:
            confidence = ConfidenceExplanation(
                decision="Fail",
                winner="none",
                reason="No non-empty body candidate was available.",
                evidence_failed=["has_text"],
                score=0.0,
            )
            return self._resolution(
                ProcessingDisposition.FAIL,
                None,
                candidates,
                confidence,
                template,
                document_hash,
            )

        valid_candidates = [candidate for candidate in candidates if self._is_candidate_valid(candidate)]

        if len(candidates) > 1 and self._equivalent(candidates):
            selected = self._best_candidate(valid_candidates or candidates)
            merged_graph = self._merge_equivalent_graphs(candidates, selected)
            selected = selected.model_copy(
                update={
                    "candidate_id": "merged_equivalent",
                    "source": "merged_equivalent",
                    "evidence_graph": merged_graph,
                }
            )
            confidence = self._confidence(
                decision="Winner",
                winner="merged_equivalent",
                graph=merged_graph,
                reason="HTML and full_text normalize to the same canonical body.",
            )
            return self._resolution(
                ProcessingDisposition.PASS,
                selected,
                candidates,
                confidence,
                template,
                document_hash,
            )

        if len(valid_candidates) == 1:
            selected = valid_candidates[0]
            conflicts = self._cross_candidate_conflicts(candidates)
            graph = selected.evidence_graph.model_copy(
                update={"conflicts": selected.evidence_graph.conflicts + conflicts}
            )
            selected = selected.model_copy(update={"evidence_graph": graph})
            confidence = self._confidence(
                decision="Winner",
                winner=selected.source,
                graph=graph,
                reason=f"{selected.source} is the only candidate with required text, boundary, and ordering evidence.",
            )
            return self._resolution(
                ProcessingDisposition.PASS,
                selected,
                candidates,
                confidence,
                template,
                document_hash,
            )

        if len(valid_candidates) > 1:
            conflicts = self._cross_candidate_conflicts(candidates)
            confidence = ConfidenceExplanation(
                decision="Ambiguous",
                winner="none",
                evidence_passed=self._combined_evidence_names(valid_candidates, passed=True),
                evidence_failed=self._combined_evidence_names(valid_candidates, passed=False),
                conflicts=conflicts or ["Multiple valid body candidates disagree."],
                reason="Multiple valid body candidates disagree and no unique winner can be proven.",
                score=0.0,
            )
            return self._resolution(
                ProcessingDisposition.AMBIGUOUS,
                None,
                candidates,
                confidence,
                template,
                document_hash,
            )

        confidence = ConfidenceExplanation(
            decision="Fail",
            winner="none",
            evidence_passed=self._combined_evidence_names(candidates, passed=True),
            evidence_failed=self._combined_evidence_names(candidates, passed=False),
            conflicts=self._cross_candidate_conflicts(candidates),
            reason="No candidate satisfied required text, boundary, and ordering evidence.",
            score=0.0,
        )
        return self._resolution(
            ProcessingDisposition.FAIL,
            None,
            candidates,
            confidence,
            template,
            document_hash,
        )

    def _build_candidates(self, doc: LegalDocumentSchema) -> List[BodyCandidate]:
        candidates: List[BodyCandidate] = []

        if (doc.full_text or "").strip():
            blocks = self.normalizer.build_plain_text_blocks(doc.full_text, doc.source, block_prefix="full")
            candidates.append(self._candidate("full_text", blocks, doc))

        if (doc.html_text or "").strip():
            try:
                blocks = self.normalizer.build_html_blocks(doc.html_text, doc.source, block_prefix="html")
                candidates.append(self._candidate("html", blocks, doc))
            except Exception as exc:
                graph = EvidenceGraph(
                    candidate_id="html",
                    source="html",
                    evidence=[
                        EvidenceNode(
                            name="parse",
                            source="html",
                            passed=False,
                            detail=f"HTML normalization failed: {exc.__class__.__name__}",
                        )
                    ],
                    conflicts=["HTML normalization failed."],
                )
                candidates.append(BodyCandidate(candidate_id="html", source="html", text="", blocks=[], evidence_graph=graph))

        return [candidate for candidate in candidates if candidate.text.strip() or candidate.evidence_graph.evidence]

    def _candidate(self, source_name: str, blocks: List[TextBlock], doc: LegalDocumentSchema) -> BodyCandidate:
        text = "\n".join(block.normalized_text for block in blocks if block.normalized_text).strip()
        body_hash = self._hash_text(text)
        evidence = self._candidate_evidence(source_name, text, blocks, doc)
        conflicts = [node.detail for node in evidence if not node.passed and node.name in {"document_number", "metadata"}]
        graph = EvidenceGraph(
            candidate_id=source_name,
            source=source_name,
            body_hash=body_hash,
            normalized_char_count=len(text),
            evidence=evidence,
            conflicts=conflicts,
        )
        return BodyCandidate(candidate_id=source_name, source=source_name, text=text, blocks=blocks, evidence_graph=graph)

    def _candidate_evidence(
        self,
        source_name: str,
        text: str,
        blocks: List[TextBlock],
        doc: LegalDocumentSchema,
    ) -> List[EvidenceNode]:
        return [
            EvidenceNode(
                name="has_text",
                source=source_name,
                passed=bool(text.strip()),
                detail="Candidate contains normalized body text." if text.strip() else "Candidate has no body text.",
                value_hash=self._hash_text(text) if text else None,
            ),
            EvidenceNode(
                name="boundary",
                source=source_name,
                passed=self._has_structural_boundary(text),
                detail="Structural boundary was found." if self._has_structural_boundary(text) else "No legal structural boundary was found.",
            ),
            EvidenceNode(
                name="metadata",
                source=source_name,
                passed=self._metadata_supported(text, doc),
                detail="Candidate agrees with available metadata." if self._metadata_supported(text, doc) else "Candidate conflicts with available metadata.",
            ),
            EvidenceNode(
                name="title",
                source=source_name,
                passed=self._title_supported(text, doc.title),
                detail="Title is absent or supported by candidate." if self._title_supported(text, doc.title) else "Title is not found in candidate text.",
            ),
            EvidenceNode(
                name="document_number",
                source=source_name,
                passed=self._document_number_supported(text, doc),
                detail="Document number is absent or supported by candidate." if self._document_number_supported(text, doc) else "Document number is not found in candidate text.",
            ),
            EvidenceNode(
                name="ordering",
                source=source_name,
                passed=self._ordered(blocks),
                detail="Blocks are in strict ascending order." if self._ordered(blocks) else "Block order is not strictly ascending.",
            ),
            EvidenceNode(
                name="hash",
                source=source_name,
                passed=bool(text.strip()),
                detail="Body hash computed." if text.strip() else "Body hash unavailable.",
                value_hash=self._hash_text(text) if text else None,
            ),
        ]

    def _is_candidate_valid(self, candidate: BodyCandidate) -> bool:
        evidence = {node.name: node.passed for node in candidate.evidence_graph.evidence}
        return bool(evidence.get("has_text") and evidence.get("boundary") and evidence.get("ordering"))

    def _equivalent(self, candidates: List[BodyCandidate]) -> bool:
        bodies = [self._canonical(candidate.text) for candidate in candidates if candidate.text.strip()]
        return bool(bodies) and len(set(bodies)) == 1

    def _best_candidate(self, candidates: List[BodyCandidate]) -> BodyCandidate:
        return sorted(candidates, key=lambda c: (self._score(c), len(c.text)), reverse=True)[0]

    def _score(self, candidate: BodyCandidate) -> float:
        nodes = candidate.evidence_graph.evidence
        if not nodes:
            return 0.0
        return sum(1 for node in nodes if node.passed) / len(nodes)

    def _confidence(
        self,
        decision: str,
        winner: str,
        graph: EvidenceGraph,
        reason: str,
    ) -> ConfidenceExplanation:
        return ConfidenceExplanation(
            decision=decision,
            winner=winner,
            evidence_passed=[node.name for node in graph.evidence if node.passed],
            evidence_failed=[node.name for node in graph.evidence if not node.passed],
            conflicts=graph.conflicts,
            reason=reason,
            score=round(sum(1 for node in graph.evidence if node.passed) / max(1, len(graph.evidence)), 3),
        )

    def _resolution(
        self,
        disposition: ProcessingDisposition,
        selected: Optional[BodyCandidate],
        candidates: List[BodyCandidate],
        confidence: ConfidenceExplanation,
        template: TemplateRegistryEntry,
        document_hash: str,
    ) -> BodyResolution:
        body_hash = selected.evidence_graph.body_hash if selected else ""
        audit_id = self._hash_text("|".join([document_hash, body_hash, template.template_id, confidence.decision, confidence.reason]))[:16]
        return BodyResolution(
            disposition=disposition,
            selected_candidate=selected,
            candidates=candidates,
            confidence=confidence,
            template=template,
            document_hash=document_hash,
            body_hash=body_hash,
            audit_id=audit_id,
        )

    def _merge_equivalent_graphs(self, candidates: List[BodyCandidate], selected: BodyCandidate) -> EvidenceGraph:
        evidence: List[EvidenceNode] = []
        conflicts: List[str] = []
        seen = set()
        for candidate in candidates:
            conflicts.extend(candidate.evidence_graph.conflicts)
            for node in candidate.evidence_graph.evidence:
                key = (node.source, node.name)
                if key not in seen:
                    evidence.append(node)
                    seen.add(key)
        return EvidenceGraph(
            candidate_id="merged_equivalent",
            source="merged_equivalent",
            body_hash=selected.evidence_graph.body_hash,
            normalized_char_count=len(selected.text),
            evidence=evidence,
            conflicts=sorted(set(conflicts)),
        )

    def _cross_candidate_conflicts(self, candidates: List[BodyCandidate]) -> List[str]:
        hashes = {candidate.source: candidate.evidence_graph.body_hash for candidate in candidates if candidate.text.strip()}
        unique_hashes = set(hashes.values())
        if len(unique_hashes) <= 1:
            return []
        return [f"Body candidates disagree: {', '.join(sorted(hashes))}."]

    def _combined_evidence_names(self, candidates: Iterable[BodyCandidate], passed: bool) -> List[str]:
        names = set()
        for candidate in candidates:
            for node in candidate.evidence_graph.evidence:
                if node.passed is passed:
                    names.add(f"{candidate.source}.{node.name}")
        return sorted(names)

    def _has_structural_boundary(self, text: str) -> bool:
        folded = self._fold(text)
        patterns = [
            r"(?m)^\s*chuong\s+\S+",
            r"(?m)^\s*muc\s+\S+",
            r"(?m)^\s*dieu\s+\d+",
            r"(?m)^\s*phu\s+luc\b",
            r"(?m)^\s*\d+\.\s+\S+",
        ]
        return any(re.search(pattern, folded, re.IGNORECASE) for pattern in patterns)

    def _metadata_supported(self, text: str, doc: LegalDocumentSchema) -> bool:
        numbers = [value for value in self._document_numbers(doc) if value]
        if not numbers:
            return True
        folded = self._fold(text)
        return any(self._fold(number) in folded for number in numbers)

    def _title_supported(self, text: str, title: str) -> bool:
        title = (title or "").strip()
        if not title or len(title) < 8:
            return True
        folded_text = self._fold(text)
        folded_title = self._fold(title)
        title_terms = [term for term in folded_title.split() if len(term) >= 4]
        if not title_terms:
            return True
        matches = sum(1 for term in title_terms if term in folded_text)
        return matches >= max(1, len(title_terms) // 2)

    def _document_number_supported(self, text: str, doc: LegalDocumentSchema) -> bool:
        numbers = [value for value in self._document_numbers(doc) if value]
        if not numbers:
            return True
        folded = self._fold(text)
        return any(self._fold(number) in folded for number in numbers)

    def _document_numbers(self, doc: LegalDocumentSchema) -> List[str]:
        values = [doc.official_number or ""]
        attrs = doc.attributes or {}
        raw_val = attrs.get("official_number")
        if isinstance(raw_val, list):
            values.extend(str(item) for item in raw_val)
        elif raw_val:
            values.append(str(raw_val))
        return [value.strip() for value in values if str(value).strip() and str(value).strip() != "UNKNOWN"]

    def _ordered(self, blocks: List[TextBlock]) -> bool:
        orders = [block.order for block in blocks]
        return orders == sorted(orders) and len(orders) == len(set(orders))

    def _document_hash(self, doc: LegalDocumentSchema) -> str:
        payload: Dict[str, Any] = {
            "source_id": doc.source_id,
            "source": doc.source,
            "url": doc.url,
            "title": doc.title,
            "full_text": doc.full_text,
            "html_text": doc.html_text,
            "attributes": doc.attributes,
            "relations": doc.relations,
            "raw_schema": doc.raw_schema,
        }
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return self._hash_text(stable)

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    def _canonical(self, text: str) -> str:
        return re.sub(r"\s+", " ", self.normalizer.normalize_text(text)).strip()

    def _fold(self, text: str) -> str:
        import unicodedata

        normalized = unicodedata.normalize("NFD", text or "")
        without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        return without_marks.replace("đ", "d").replace("Đ", "D").lower()
