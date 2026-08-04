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
    # Match document numbers like "72/2020/QH14", "10/2021/TT-BTNMT", "08/2022/NĐ-CP"
    doc_nums = re.findall(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", text, re.IGNORECASE)
    articles = re.findall(r"\bĐiều\s+\d+[A-Za-z]?\b", text, re.IGNORECASE)
    clauses = re.findall(r"\bKhoản\s+\d+\b", text, re.IGNORECASE)

    doc_num = doc_nums[0].upper() if doc_nums else ""
    art = articles[0] if articles else ""
    cl = clauses[0] if clauses else ""
    if doc_num or art or cl:
        citations.append({
            "document_number": doc_num,
            "article": art,
            "clause": cl,
        })
    return citations


def find_document_candidates(
    conn: sqlite3.Connection,
    fts_index: LegalFtsIndex,
    doc_num_hint: str,
    snippet: str,
) -> List[int]:
    candidate_ids: List[int] = []
    seen: set[int] = set()

    def add_ids(ids: Iterable[int]) -> None:
        for cid in ids:
            if cid not in seen:
                candidate_ids.append(cid)
                seen.add(cid)

    # 1. Exact document_number match in SQLite metadata
    if doc_num_hint:
        norm_num = normalize_document_number(doc_num_hint)
        cur = conn.execute(
            "SELECT document_id FROM metadata WHERE UPPER(REPLACE(document_number, ' ', '')) = ?",
            (norm_num,),
        )
        add_ids(row[0] for row in cur.fetchall())

    # 2. FTS search by document number
    if doc_num_hint:
        add_ids(fts_index.search(doc_num_hint, limit=20))

    # 3. Check for document numbers inside snippet if hint was missing
    if not candidate_ids and not doc_num_hint:
        extracted_snip = extract_legal_citations_from_text(snippet)
        if extracted_snip and extracted_snip[0]["document_number"]:
            snip_doc_num = extracted_snip[0]["document_number"]
            norm_num = normalize_document_number(snip_doc_num)
            cur = conn.execute(
                "SELECT document_id FROM metadata WHERE UPPER(REPLACE(document_number, ' ', '')) = ?",
                (norm_num,),
            )
            add_ids(row[0] for row in cur.fetchall())
            add_ids(fts_index.search(snip_doc_num, limit=20))

    return candidate_ids


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

    # Statistical counters by case and by evidence item
    type_counts: Dict[str, int] = {}
    case_status_counts: Dict[str, int] = {}
    evidence_status_counts: Dict[str, int] = {}
    confidence_counts: Dict[str, int] = {}

    verified_doc_count = 0
    verified_art_count = 0
    verified_clause_count = 0
    multi_hop_all_covered = 0
    multi_hop_total = 0
    duplicate_questions: Dict[str, int] = {}

    for idx, case in enumerate(cases, start=1):
        if idx % 50 == 0 or idx == 1 or idx == len(cases):
            print(f"Auditing case {idx}/{len(cases)}...", flush=True)

        case_id = f"case_{idx:03d}"
        q_text = case.get("question", "").strip()
        q_type = case.get("question_type", "factoid")
        gt_ans = case.get("ground_truth_answer", "").strip()
        gt_contexts = case.get("ground_truth_context", [])

        type_counts[q_type] = type_counts.get(q_type, 0) + 1
        duplicate_questions[q_text] = duplicate_questions.get(q_text, 0) + 1

        is_unanswerable = (q_type == "unanswerable" or "tài liệu không đề cập" in norm_text(gt_ans))

        case_labels: List[Dict[str, Any]] = []

        if is_unanswerable:
            label = {
                "case_id": case_id,
                "status": "unanswerable",
                "document_id": None,
                "document_number": None,
                "article": None,
                "clause": None,
                "required": False,
                "verification_method": "unanswerable_ground_truth",
                "verification_confidence": "unverified",
                "matching_document_count": 0,
                "reference_anchor_hash": None,
                "diagnostics": {},
                "notes": "Explicit unanswerable case — no gold document assigned",
            }
            case_labels.append(label)
            evidence_status_counts["unanswerable"] = evidence_status_counts.get("unanswerable", 0) + 1
            confidence_counts["unverified"] = confidence_counts.get("unverified", 0) + 1
            case_status_counts["unanswerable"] = case_status_counts.get("unanswerable", 0) + 1
        else:
            if q_type == "multi-hop":
                multi_hop_total += 1

            all_snippets_verified = True
            for snip_idx, snippet in enumerate(gt_contexts, start=1):
                norm_snip = norm_text(snippet)
                anchor_hash = hashlib.sha256(norm_snip.encode("utf-8")).hexdigest()[:16]

                extracted_cites = extract_legal_citations_from_text(q_text + " " + gt_ans + " " + snippet)
                doc_num_hint = extracted_cites[0]["document_number"] if extracted_cites else ""
                art_hint = extracted_cites[0]["article"] if extracted_cites else ""
                cl_hint = extracted_cites[0]["clause"] if extracted_cites else ""

                candidate_ids = find_document_candidates(conn, fts_index, doc_num_hint, norm_snip)
                retrieved_docs = content_store.get_many(candidate_ids) if candidate_ids else {}

                # Full normalized anchor matching (no 30/60-char truncated prefix!)
                matching_docs = []
                for doc_id, doc in retrieved_docs.items():
                    norm_content = norm_text(doc.content)
                    if norm_snip in norm_content:
                        matching_docs.append((doc_id, doc))

                match_count = len(matching_docs)

                diagnostics: Dict[str, Any] = {
                    "extracted_doc_number": doc_num_hint,
                    "extracted_article": art_hint,
                    "extracted_clause": cl_hint,
                    "candidate_doc_count": len(candidate_ids),
                    "exact_full_anchor_matches": match_count,
                }

                # Mutually exclusive precedence assignment
                if not extracted_cites and match_count == 0:
                    primary_status = "no_citation_extracted"
                    confidence = "unverified"
                    all_snippets_verified = False
                    label = {
                        "case_id": case_id,
                        "status": primary_status,
                        "document_id": None,
                        "document_number": None,
                        "article": art_hint or None,
                        "clause": cl_hint or None,
                        "required": True,
                        "verification_method": "deterministic_audit",
                        "verification_confidence": confidence,
                        "matching_document_count": 0,
                        "reference_anchor_hash": anchor_hash,
                        "diagnostics": diagnostics,
                        "notes": "No citation extracted and no matching content anchor found",
                    }
                elif match_count == 1:
                    matched_id, matched_doc = matching_docs[0]
                    chunks = chunk_document(matched_doc.metadata, matched_doc.content)
                    matched_chunk = None
                    for chk in chunks:
                        if norm_snip in norm_text(chk.text):
                            matched_chunk = chk
                            break

                    art_val = matched_chunk.article if matched_chunk else art_hint
                    cl_val = matched_chunk.clause if matched_chunk else cl_hint

                    primary_status = "verified"
                    confidence = "exact_doc_number_and_anchor"
                    label = {
                        "case_id": case_id,
                        "status": primary_status,
                        "document_id": matched_id,
                        "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                        "article": art_val,
                        "clause": cl_val,
                        "required": True,
                        "verification_method": "exact_content_store_full_anchor_match",
                        "verification_confidence": confidence,
                        "matching_document_count": 1,
                        "reference_anchor_hash": anchor_hash,
                        "diagnostics": diagnostics,
                        "notes": f"Verified in doc {matched_id}",
                    }
                    verified_doc_count += 1
                    if art_val:
                        verified_art_count += 1
                    if cl_val:
                        verified_clause_count += 1

                elif match_count > 1:
                    matched_id, matched_doc = matching_docs[0]
                    chunks = chunk_document(matched_doc.metadata, matched_doc.content)
                    matched_chunk = None
                    for chk in chunks:
                        if norm_snip in norm_text(chk.text):
                            matched_chunk = chk
                            break

                    primary_status = "ambiguous"
                    confidence = "ambiguous"
                    all_snippets_verified = False
                    label = {
                        "case_id": case_id,
                        "status": primary_status,
                        "document_id": matched_id,
                        "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                        "article": matched_chunk.article if matched_chunk else art_hint,
                        "clause": matched_chunk.clause if matched_chunk else cl_hint,
                        "required": True,
                        "verification_method": "content_store_multi_match",
                        "verification_confidence": confidence,
                        "matching_document_count": match_count,
                        "reference_anchor_hash": anchor_hash,
                        "diagnostics": diagnostics,
                        "notes": f"Ambiguous: matched {match_count} documents",
                    }
                else:  # match_count == 0
                    if candidate_ids:
                        primary_status = "document_found_anchor_not_found"
                    elif doc_num_hint:
                        primary_status = "document_number_not_found"
                    else:
                        primary_status = "not_found_by_local_deterministic_audit"
                    confidence = "unverified"
                    all_snippets_verified = False
                    label = {
                        "case_id": case_id,
                        "status": primary_status,
                        "document_id": None,
                        "document_number": doc_num_hint or None,
                        "article": art_hint or None,
                        "clause": cl_hint or None,
                        "required": True,
                        "verification_method": "content_store_search",
                        "verification_confidence": confidence,
                        "matching_document_count": 0,
                        "reference_anchor_hash": anchor_hash,
                        "diagnostics": diagnostics,
                        "notes": f"Ground truth anchor not found in local corpus (hint: {doc_num_hint})",
                    }

                case_labels.append(label)
                evidence_status_counts[primary_status] = evidence_status_counts.get(primary_status, 0) + 1
                confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

            # Case-level status
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

    # Save v2 sidecar JSON with schema_version: 2.0.0
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

    # Generate applicability report v2
    dups_count = sum(cnt - 1 for cnt in duplicate_questions.values() if cnt > 1)
    report_lines = []
    report_lines.append("# GOLDEN DATASET APPLICABILITY REPORT V2 — namsyntax_legal_qa_420")
    report_lines.append("")
    report_lines.append("**Dataset**: `app/data/namsyntax_legal_qa_420.json`  ")
    report_lines.append(f"**Total Test Cases**: `{len(cases)}`  ")
    report_lines.append(f"**Total Evidence Items**: `{len(labels_sidecar)}`  ")
    report_lines.append(f"**Sidecar Labels V2**: `{sidecar_path}`  ")
    report_lines.append("**Schema Version**: `2.0.0`  ")
    report_lines.append("")

    report_lines.append("## 1. Dataset Breakdown by Question Type")
    report_lines.append("")
    report_lines.append("| Question Type | Case Count | Percentage |")
    report_lines.append("| :--- | ---: | ---: |")
    for qt, cnt in type_counts.items():
        report_lines.append(f"| `{qt}` | {cnt} | {cnt / len(cases) * 100:.1f}% |")
    report_lines.append("")

    report_lines.append("## 2. Deterministic Verification Counts (by Evidence Item)")
    report_lines.append("")
    report_lines.append("| Evidence Status | Item Count | % of Evidence Items | Description |")
    report_lines.append("| :--- | ---: | ---: | :--- |")
    for st, cnt in sorted(evidence_status_counts.items(), key=lambda x: -x[1]):
        report_lines.append(f"| `{st}` | {cnt} | {cnt / len(labels_sidecar) * 100:.1f}% | Items with status {st} |")
    report_lines.append("")

    report_lines.append("## 3. Case-Level Verification Summary")
    report_lines.append("")
    report_lines.append("| Case Verification Category | Case Count | % of Test Cases |")
    report_lines.append("| :--- | ---: | ---: |")
    for cst, cnt in sorted(case_status_counts.items(), key=lambda x: -x[1]):
        report_lines.append(f"| `{cst}` | {cnt} | {cnt / len(cases) * 100:.1f}% |")
    report_lines.append("")

    report_lines.append("## 4. Verification Confidence Breakdown")
    report_lines.append("")
    report_lines.append("| Confidence Identifier | Item Count | Description |")
    report_lines.append("| :--- | ---: | :--- |")
    for conf, cnt in confidence_counts.items():
        report_lines.append(f"| `{conf}` | {cnt} | Verification confidence level {conf} |")
    report_lines.append("")

    report_lines.append("## 5. Detailed Metric Counters")
    report_lines.append("")
    report_lines.append(f"- **Verified Document Labels**: `{verified_doc_count}`")
    report_lines.append(f"- **Verified Article Labels**: `{verified_art_count}`")
    report_lines.append(f"- **Verified Clause Labels**: `{verified_clause_count}`")
    report_lines.append(f"- **Multi-Hop All-Evidence Verified**: `{multi_hop_all_covered} / {multi_hop_total}`")
    report_lines.append(f"- **Duplicate Question Text**: `{dups_count}`")
    report_lines.append("")

    report_path = Path("docs/evaluation/golden_dataset_applicability_report_v2.md")
    with report_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"Saved applicability report v2 to {report_path}")

    return {
        "sidecar_path": str(sidecar_path),
        "report_path": str(report_path),
        "total_cases": len(cases),
        "total_evidence_items": len(labels_sidecar),
        "evidence_status_counts": evidence_status_counts,
        "case_status_counts": case_status_counts,
    }


if __name__ == "__main__":
    audit_golden_dataset()
