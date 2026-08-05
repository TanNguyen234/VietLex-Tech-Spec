from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config import get_settings
from app.evaluation.schemas import EvidenceStatus, RequiredLevel
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex, normalize_document_number
from app.ingestion.legal_text import chunk_document


def norm_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.casefold().split())


def extract_legal_citations_from_text(text: str) -> List[Dict[str, str]]:
    citations = []
    doc_nums = [(m.start(), m.group().upper()) for m in re.finditer(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", text, re.IGNORECASE)]
    articles = [(m.start(), m.group()) for m in re.finditer(r"\bĐiều\s+\d+[A-Za-z]?\b", text, re.IGNORECASE)]
    clauses = [(m.start(), m.group()) for m in re.finditer(r"\bKhoản\s+\d+\b", text, re.IGNORECASE)]

    if not doc_nums and not articles and not clauses:
        return citations

    if not doc_nums:
        citations.append({
            "document_number": "",
            "article": articles[0][1] if articles else "",
            "clause": clauses[0][1] if clauses else ""
        })
        return citations

    for doc_pos, doc_num in doc_nums:
        assoc_art = ""
        assoc_cl = ""
        
        best_art = None
        for art_pos, art in articles:
            if art_pos < doc_pos and (doc_pos - art_pos) < 100:
                best_art = art
        if best_art:
            assoc_art = best_art
            
        best_cl = None
        for cl_pos, cl in clauses:
            if cl_pos < doc_pos and (doc_pos - cl_pos) < 150:
                best_cl = cl
        if best_cl:
            assoc_cl = best_cl
            
        cit = {
            "document_number": doc_num,
            "article": assoc_art,
            "clause": assoc_cl
        }
        if cit not in citations:
            citations.append(cit)
            
    return citations


def resolve_document_identity(
    conn: sqlite3.Connection,
    fts_index: LegalFtsIndex,
    doc_id_hint: Optional[int],
    source_url_hint: Optional[str],
    doc_num_hint: Optional[str],
) -> Tuple[List[int], str, List[str], bool]:
    hint_sources: List[str] = []
    candidate_ids: List[int] = []
    identity_method = "none"
    is_complete_search = True

    # 1. Exact document ID
    if doc_id_hint is not None:
        hint_sources.append("dataset_reference_doc_id")
        cur = conn.execute("SELECT document_id FROM metadata WHERE document_id = ?", (doc_id_hint,))
        rows = cur.fetchall()
        if rows:
            candidate_ids = [rows[0][0]]
            identity_method = "exact_doc_id"
            return candidate_ids, identity_method, hint_sources, True

    # 2. Exact normalized source URL
    if source_url_hint:
        hint_sources.append("dataset_reference_source_url")
        cur = conn.execute("SELECT document_id FROM metadata WHERE source_url = ?", (source_url_hint.strip(),))
        rows = cur.fetchall()
        if rows:
            candidate_ids = [r[0] for r in rows]
            identity_method = "exact_source_url"
            return candidate_ids, identity_method, hint_sources, True

    # 3. Exact normalized document number against COMPLETE metadata index
    if doc_num_hint:
        hint_sources.append("dataset_reference_doc_number")
        norm_num = normalize_document_number(doc_num_hint)
        cur = conn.execute(
            "SELECT document_id FROM metadata WHERE UPPER(REPLACE(document_number, ' ', '')) = ?",
            (norm_num,),
        )
        rows = cur.fetchall()
        if rows:
            candidate_ids = [r[0] for r in rows]
            identity_method = "exact_metadata_doc_number"
            return candidate_ids, identity_method, hint_sources, True

    # 4. Fallback lexical discovery (unverified candidate generation only)
    if doc_num_hint:
        candidate_ids = fts_index.search(doc_num_hint, limit=20)
        if candidate_ids:
            identity_method = "lexical_candidate_fallback"
            is_complete_search = False
            return candidate_ids, identity_method, hint_sources, False

    return [], "not_applicable", hint_sources, True


def check_anchor_match(snippet: str, content: str) -> Tuple[bool, str, Dict[str, Any]]:
    norm_snip = norm_text(snippet)
    norm_content = norm_text(content)

    if norm_snip in norm_content:
        return True, "full_anchor_exact", {"full_anchor_matched": True}

    words = norm_snip.split()
    if len(words) >= 20:
        win_beg = " ".join(words[:12])
        win_mid = " ".join(words[len(words) // 2 - 6 : len(words) // 2 + 6])
        win_end = " ".join(words[-12:])

        w_beg_match = win_beg in norm_content
        w_mid_match = win_mid in norm_content
        w_end_match = win_end in norm_content

        match_count = sum([w_beg_match, w_mid_match, w_end_match])
        window_diag = {
            "window_beg_hash": hashlib.sha256(win_beg.encode("utf-8")).hexdigest()[:8],
            "window_mid_hash": hashlib.sha256(win_mid.encode("utf-8")).hexdigest()[:8],
            "window_end_hash": hashlib.sha256(win_end.encode("utf-8")).hexdigest()[:8],
            "windows_matched": match_count,
        }
        if match_count >= 2:
            return True, "multi_window_agreement", window_diag

    return False, "none", {}


def decide_evidence_verification(
    req_level: RequiredLevel,
    art_hint: str,
    cl_hint: str,
    matched_chunk,
) -> tuple[EvidenceStatus, Optional[str], Optional[str]]:
    if not matched_chunk:
        return EvidenceStatus.STRUCTURAL_ANCHOR_NOT_FOUND, None, None

    art_val = matched_chunk.article
    cl_val = matched_chunk.clause

    doc_matched = True
    art_matched = bool(art_hint and art_val and norm_text(art_hint) == norm_text(art_val))
    cl_matched = bool(cl_hint and cl_val and norm_text(cl_hint) == norm_text(cl_val))

    if req_level == RequiredLevel.DOCUMENT:
        return EvidenceStatus.VERIFIED, art_val, cl_val
    elif req_level == RequiredLevel.ARTICLE:
        if art_matched:
            return EvidenceStatus.VERIFIED, art_val, cl_val
        if not art_hint:
            return EvidenceStatus.VERIFIED, art_val, cl_val
        return EvidenceStatus.DOCUMENT_VERIFIED_ARTICLE_UNRESOLVED, art_val, cl_val
    elif req_level == RequiredLevel.CLAUSE:
        if art_matched and cl_matched:
            return EvidenceStatus.VERIFIED, art_val, cl_val
        if art_matched and not cl_hint:
            return EvidenceStatus.VERIFIED, art_val, cl_val
        if not art_hint and not cl_hint:
            return EvidenceStatus.VERIFIED, art_val, cl_val
        if art_matched:
            return EvidenceStatus.ARTICLE_VERIFIED_CLAUSE_UNRESOLVED, art_val, cl_val
        return EvidenceStatus.DOCUMENT_VERIFIED_ARTICLE_UNRESOLVED, art_val, cl_val
        
    return EvidenceStatus.STRUCTURAL_ANCHOR_NOT_FOUND, art_val, cl_val


def audit_golden_dataset() -> Dict[str, Any]:
    settings = get_settings()
    dataset_path = Path("app/data/namsyntax_legal_qa_420.json")
    if not dataset_path.exists():
        print(f"BLOCKED: Dataset {dataset_path} not found.")
        sys.exit(1)

    db_path = Path(settings.CONTENT_STORE_PATH)
    fts_path = Path(settings.LEGAL_FTS_PATH)
    if not db_path.exists() or not fts_path.exists():
        print(f"BLOCKED: Content store {db_path} or FTS index {fts_path} unavailable.")
        sys.exit(1)

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT COUNT(*) FROM metadata")
        doc_count = cur.fetchone()[0]
        if doc_count <= 0:
            print("BLOCKED: Local content store is empty.")
            sys.exit(1)
    except Exception as err:
        print(f"BLOCKED: Local content store database error: {err}")
        sys.exit(1)

    with dataset_path.open("r", encoding="utf-8") as f:
        cases = json.load(f)

    content_store = ContentStore(settings.CONTENT_STORE_PATH)
    fts_index = LegalFtsIndex(
        store=content_store,
        path=settings.LEGAL_FTS_PATH,
        dataset_revision=settings.DATASET_REVISION,
    )

    print(f"Auditing {len(cases)} cases from {dataset_path} against {doc_count:,}-doc local content store...")

    labels_sidecar: List[Dict[str, Any]] = []

    type_counts: Dict[str, int] = {}
    evidence_status_counts: Dict[str, int] = {}
    case_status_counts: Dict[str, int] = {}
    confidence_counts: Dict[str, int] = {}

    verified_doc_count = 0
    verified_art_count = 0
    verified_clause_count = 0
    multi_hop_all_covered = 0
    multi_hop_total = 0
    seen_evidence_ids: set[str] = set()

    for idx, case in enumerate(cases, start=1):
        case_id = f"case_{idx:03d}"
        q_text = case.get("question", "").strip()
        q_type = case.get("question_type", "factoid")
        gt_ans = case.get("ground_truth_answer", "").strip()
        gt_contexts = case.get("ground_truth_context", [])

        type_counts[q_type] = type_counts.get(q_type, 0) + 1

        is_unanswerable = (q_type == "unanswerable" or "tài liệu không đề cập" in norm_text(gt_ans))
        case_labels: List[Dict[str, Any]] = []

        if is_unanswerable:
            ev_id = f"{case_id}_ev_01"
            if ev_id in seen_evidence_ids:
                raise ValueError(f"Duplicate evidence_item_id: {ev_id}")
            seen_evidence_ids.add(ev_id)

            label = {
                "evidence_item_id": ev_id,
                "case_id": case_id,
                "context_index": 0,
                "citation_index": 0,
                "reference_anchor_hash": None,
                "status": EvidenceStatus.UNANSWERABLE.value,
                "document_id": None,
                "document_number": None,
                "article": None,
                "clause": None,
                "required": False,
                "required_level": RequiredLevel.ARTICLE.value,
                "verification_confidence": "unverified",
                "candidate_generation_method": "unanswerable",
                "document_identity_method": "not_applicable",
                "candidate_count_before_anchor": 0,
                "corpus_search_limit": doc_count,
                "anchor_match_method": "none",
                "identity_hint_sources": [],
                "is_metadata_search_complete": True,
            }
            case_labels.append(label)
            evidence_status_counts[EvidenceStatus.UNANSWERABLE.value] = (
                evidence_status_counts.get(EvidenceStatus.UNANSWERABLE.value, 0) + 1
            )
            confidence_counts["unverified"] = confidence_counts.get("unverified", 0) + 1
            case_status_counts["unanswerable"] = case_status_counts.get("unanswerable", 0) + 1
        else:
            if q_type == "multi-hop":
                multi_hop_total += 1

            all_snippets_verified = True

            for ctx_idx, snippet in enumerate(gt_contexts, start=1):
                norm_snip = norm_text(snippet)
                anchor_hash = hashlib.sha256(norm_snip.encode("utf-8")).hexdigest()[:16]

                extracted_cites = extract_legal_citations_from_text(q_text + " " + gt_ans + " " + snippet)
                if not extracted_cites:
                    extracted_cites = [{"document_number": "", "article": "", "clause": ""}]

                for cit_idx, cite in enumerate(extracted_cites, start=1):
                    ev_id = f"{case_id}_ctx{ctx_idx:02d}_cit{cit_idx:02d}"
                    if ev_id in seen_evidence_ids:
                        raise ValueError(f"Duplicate evidence_item_id: {ev_id}")
                    seen_evidence_ids.add(ev_id)

                    doc_num_hint = cite.get("document_number", "")
                    art_hint = cite.get("article", "")
                    cl_hint = cite.get("clause", "")

                    if cl_hint:
                        req_level = RequiredLevel.CLAUSE
                    elif art_hint:
                        req_level = RequiredLevel.ARTICLE
                    else:
                        req_level = RequiredLevel.DOCUMENT

                    candidate_ids, identity_method, hint_sources, is_search_complete = resolve_document_identity(
                        conn, fts_index, None, None, doc_num_hint
                    )

                    retrieved_docs = content_store.get_many(candidate_ids) if candidate_ids else {}

                    matching_docs = []
                    for doc_id, doc in retrieved_docs.items():
                        matched, match_type, window_diag = check_anchor_match(norm_snip, doc.content)
                        if matched:
                            matching_docs.append((doc_id, doc, match_type, window_diag))

                    match_count = len(matching_docs)

                    if not doc_num_hint and match_count == 0:
                        primary_status = EvidenceStatus.NO_CITATION_EXTRACTED
                        confidence = "unverified"
                        all_snippets_verified = False
                        label = {
                            "evidence_item_id": ev_id,
                            "case_id": case_id,
                            "context_index": ctx_idx,
                            "citation_index": cit_idx,
                            "reference_anchor_hash": anchor_hash,
                            "status": primary_status.value,
                            "document_id": None,
                            "document_number": None,
                            "article": art_hint or None,
                            "clause": cl_hint or None,
                            "required": True,
                            "required_level": req_level.value,
                            "verification_confidence": confidence,
                            "candidate_generation_method": "none",
                            "document_identity_method": identity_method,
                            "candidate_count_before_anchor": len(candidate_ids),
                            "corpus_search_limit": doc_count,
                            "anchor_match_method": "none",
                            "identity_hint_sources": hint_sources,
                            "is_metadata_search_complete": is_search_complete,
                        }
                    elif match_count == 1:
                        matched_id, matched_doc, match_type, window_diag = matching_docs[0]

                        # Check structural chunk for article/clause matching
                        chunks = chunk_document(matched_doc.metadata, matched_doc.content)
                        matched_chunk = None
                        for chk in chunks:
                            chk_matched, _, _ = check_anchor_match(norm_snip, chk.text)
                            if chk_matched:
                                matched_chunk = chk
                                break

                        primary_status, art_val, cl_val = decide_evidence_verification(
                            req_level, art_hint, cl_hint, matched_chunk
                        )

                        confidence = (
                            "exact_doc_number_and_anchor"
                            if match_type == "full_anchor_exact"
                            else "exact_doc_number_and_multi_window_anchor"
                        )
                        if primary_status != EvidenceStatus.VERIFIED:
                            all_snippets_verified = False

                        label = {
                            "evidence_item_id": ev_id,
                            "case_id": case_id,
                            "context_index": ctx_idx,
                            "citation_index": cit_idx,
                            "reference_anchor_hash": anchor_hash,
                            "status": primary_status.value,
                            "document_id": matched_id,
                            "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                            "article": art_val,
                            "clause": cl_val,
                            "required": True,
                            "required_level": req_level.value,
                            "verification_confidence": confidence,
                            "candidate_generation_method": "metadata_search",
                            "document_identity_method": identity_method,
                            "candidate_count_before_anchor": len(candidate_ids),
                            "corpus_search_limit": doc_count,
                            "anchor_match_method": match_type,
                            "identity_hint_sources": hint_sources,
                            "is_metadata_search_complete": is_search_complete,
                        }
                        if primary_status == EvidenceStatus.VERIFIED:
                            verified_doc_count += 1
                            if art_val:
                                verified_art_count += 1
                            if cl_val:
                                verified_clause_count += 1

                    elif match_count > 1:
                        matched_id, matched_doc, match_type, window_diag = matching_docs[0]
                        primary_status = EvidenceStatus.AMBIGUOUS
                        confidence = "ambiguous"
                        all_snippets_verified = False
                        label = {
                            "evidence_item_id": ev_id,
                            "case_id": case_id,
                            "context_index": ctx_idx,
                            "citation_index": cit_idx,
                            "reference_anchor_hash": anchor_hash,
                            "status": primary_status.value,
                            "document_id": matched_id,
                            "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                            "article": art_hint or None,
                            "clause": cl_hint or None,
                            "required": True,
                            "required_level": req_level.value,
                            "verification_confidence": confidence,
                            "candidate_generation_method": "metadata_search",
                            "document_identity_method": identity_method,
                            "candidate_count_before_anchor": len(candidate_ids),
                            "corpus_search_limit": doc_count,
                            "anchor_match_method": match_type,
                            "identity_hint_sources": hint_sources,
                            "is_metadata_search_complete": is_search_complete,
                        }
                    else:  # match_count == 0
                        primary_status = EvidenceStatus.NOT_FOUND_BY_LOCAL_DETERMINISTIC_AUDIT
                        confidence = "unverified"
                        all_snippets_verified = False
                        label = {
                            "evidence_item_id": ev_id,
                            "case_id": case_id,
                            "context_index": ctx_idx,
                            "citation_index": cit_idx,
                            "reference_anchor_hash": anchor_hash,
                            "status": primary_status.value,
                            "document_id": None,
                            "document_number": doc_num_hint or None,
                            "article": art_hint or None,
                            "clause": cl_hint or None,
                            "required": True,
                            "required_level": req_level.value,
                            "verification_confidence": confidence,
                            "candidate_generation_method": "metadata_search",
                            "document_identity_method": identity_method,
                            "candidate_count_before_anchor": len(candidate_ids),
                            "corpus_search_limit": doc_count,
                            "anchor_match_method": "none",
                            "identity_hint_sources": hint_sources,
                            "is_metadata_search_complete": is_search_complete,
                        }

                    case_labels.append(label)
                    evidence_status_counts[primary_status.value] = (
                        evidence_status_counts.get(primary_status.value, 0) + 1
                    )
                    confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

            case_statuses = set(lbl["status"] for lbl in case_labels)
            if "verified" in case_statuses and len(case_statuses) == 1:
                case_status_counts["all_verified"] = case_status_counts.get("all_verified", 0) + 1
            elif "verified" in case_statuses:
                case_status_counts["partially_verified"] = case_status_counts.get("partially_verified", 0) + 1
            else:
                primary_case_st = case_labels[0]["status"] if case_labels else "unverified"
                case_status_counts[primary_case_st] = case_status_counts.get(primary_case_st, 0) + 1

            if q_type == "multi-hop" and all_snippets_verified and len(gt_contexts) > 1:
                multi_hop_all_covered += 1

        labels_sidecar.extend(case_labels)

    conn.close()

    assert len(labels_sidecar) == len(seen_evidence_ids), "Declared evidence count != unique evidence IDs"
    assert sum(evidence_status_counts.values()) == len(labels_sidecar), "Sum of evidence statuses != evidence count"

    sidecar_dir = Path("docs/evaluation/gold_labels")
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = sidecar_dir / "namsyntax_legal_qa_420_labels_v2.json"

    sidecar_payload = {
        "schema_version": "2.0.0",
        "dataset_name": "namsyntax_legal_qa_420",
        "total_cases": len(cases),
        "total_evidence_items": len(labels_sidecar),
        "labels": labels_sidecar,
    }

    with sidecar_path.open("w", encoding="utf-8") as f:
        json.dump(sidecar_payload, f, ensure_ascii=False, indent=2)
    print(f"Saved v2 sidecar labels to {sidecar_path}")

    # Summary JSON
    summary_path = sidecar_dir / "namsyntax_legal_qa_420_audit_summary_v2.json"
    summary_payload = {
        "schema_version": "2.0.0",
        "total_cases": len(cases),
        "total_evidence_items": len(labels_sidecar),
        "verified_evidence_items": verified_doc_count,
        "verified_doc_count": verified_doc_count,
        "verified_art_count": verified_art_count,
        "verified_clause_count": verified_clause_count,
        "unanswerable_cases": type_counts.get("unanswerable", 0),
        "question_type_counts": type_counts,
        "evidence_status_counts": evidence_status_counts,
        "case_status_counts": case_status_counts,
        "confidence_counts": confidence_counts,
        "multi_hop_stats": {
            "total_multi_hop": multi_hop_total,
            "all_required_covered": multi_hop_all_covered,
        },
    }
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)
    print(f"Saved audit summary to {summary_path}")

    return summary_payload


if __name__ == "__main__":
    audit_golden_dataset()
