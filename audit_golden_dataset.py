from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.ingestion.content_store import ContentStore
from app.ingestion.legal_fts import LegalFtsIndex, normalize_document_number
from app.ingestion.legal_text import chunk_document


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

    # 2. FTS search by document number or query terms
    if doc_num_hint:
        add_ids(fts_index.search(doc_num_hint, limit=20))

    # 3. FTS search using snippet key phrases
    snippet_words = [w for w in re.findall(r"[^\W_]+", snippet.casefold(), re.UNICODE) if len(w) > 3]
    if snippet_words:
        fts_query_str = " ".join(snippet_words[:6])
        add_ids(fts_index.search(fts_query_str, limit=20))

    return candidate_ids


def audit_golden_dataset() -> None:
    settings = get_settings()
    dataset_path = Path("app/data/namsyntax_legal_qa_420.json")
    if not dataset_path.exists():
        print(f"Error: Dataset {dataset_path} not found.")
        return

    with dataset_path.open("r", encoding="utf-8") as f:
        cases = json.load(f)

    content_store = ContentStore(settings.CONTENT_STORE_PATH)
    fts_index = LegalFtsIndex(
        store=content_store,
        path=settings.LEGAL_FTS_PATH,
        dataset_revision=settings.DATASET_REVISION,
    )

    db_path = settings.CONTENT_STORE_PATH
    conn = sqlite3.connect(db_path)

    print(f"Auditing {len(cases)} cases from {dataset_path} against 518,255-doc local content store...")

    labels_sidecar: List[Dict[str, Any]] = []
    
    # Statistical counters
    type_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    verified_doc_count = 0
    verified_art_count = 0
    verified_clause_count = 0
    multi_hop_all_covered = 0
    multi_hop_total = 0
    duplicate_questions: Dict[str, int] = {}

    for idx, case in enumerate(cases, start=1):
        case_id = f"case_{idx:03d}"
        q_text = case.get("question", "").strip()
        q_type = case.get("question_type", "factoid")
        gt_ans = case.get("ground_truth_answer", "").strip()
        gt_contexts = case.get("ground_truth_context", [])

        type_counts[q_type] = type_counts.get(q_type, 0) + 1
        duplicate_questions[q_text] = duplicate_questions.get(q_text, 0) + 1

        is_unanswerable = (q_type == "unanswerable" or "tài liệu không đề cập" in gt_ans.casefold())

        case_labels = []

        if is_unanswerable:
            case_labels.append({
                "case_id": case_id,
                "status": "unanswerable",
                "document_id": None,
                "document_number": None,
                "article": None,
                "clause": None,
                "required": False,
                "verification_method": "unanswerable_ground_truth",
                "matching_document_count": 0,
                "reference_anchor_hash": None,
                "notes": "Explicit unanswerable case — no gold document assigned",
            })
            status_counts["unanswerable"] = status_counts.get("unanswerable", 0) + 1
        else:
            if q_type == "multi-hop":
                multi_hop_total += 1

            all_snippets_verified = True
            for snip_idx, snippet in enumerate(gt_contexts, start=1):
                snippet_clean = " ".join(snippet.split())
                anchor_hash = hashlib.sha256(snippet_clean.encode("utf-8")).hexdigest()[:16]

                extracted_cites = extract_legal_citations_from_text(q_text + " " + gt_ans + " " + snippet_clean)
                doc_num_hint = extracted_cites[0]["document_number"] if extracted_cites else ""
                art_hint = extracted_cites[0]["article"] if extracted_cites else ""
                cl_hint = extracted_cites[0]["clause"] if extracted_cites else ""

                candidate_ids = find_document_candidates(conn, fts_index, doc_num_hint, snippet_clean)
                retrieved_docs = content_store.get_many(candidate_ids) if candidate_ids else {}

                snippet_prefix = snippet_clean[:60]
                matching_docs = []
                for doc_id, doc in retrieved_docs.items():
                    if snippet_prefix.casefold() in doc.content.casefold() or snippet_clean[:30].casefold() in doc.content.casefold():
                        matching_docs.append((doc_id, doc))

                match_count = len(matching_docs)

                if match_count == 1:
                    matched_id, matched_doc = matching_docs[0]
                    chunks = chunk_document(matched_doc.metadata, matched_doc.content)
                    matched_chunk = None
                    for chk in chunks:
                        if snippet_prefix.casefold() in chk.text.casefold() or snippet_clean[:30].casefold() in chk.text.casefold():
                            matched_chunk = chk
                            break

                    art_val = matched_chunk.article if matched_chunk else art_hint
                    cl_val = matched_chunk.clause if matched_chunk else cl_hint

                    case_labels.append({
                        "case_id": case_id,
                        "status": "verified",
                        "document_id": matched_id,
                        "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                        "article": art_val,
                        "clause": cl_val,
                        "required": True,
                        "verification_method": "exact_content_store_match",
                        "matching_document_count": 1,
                        "reference_anchor_hash": anchor_hash,
                        "notes": f"Verified in doc {matched_id}",
                    })
                    verified_doc_count += 1
                    if art_val:
                        verified_art_count += 1
                    if cl_val:
                        verified_clause_count += 1
                    status_counts["verified"] = status_counts.get("verified", 0) + 1

                elif match_count > 1:
                    matched_id, matched_doc = matching_docs[0]
                    chunks = chunk_document(matched_doc.metadata, matched_doc.content)
                    matched_chunk = None
                    for chk in chunks:
                        if snippet_prefix.casefold() in chk.text.casefold():
                            matched_chunk = chk
                            break
                    case_labels.append({
                        "case_id": case_id,
                        "status": "ambiguous",
                        "document_id": matched_id,
                        "document_number": getattr(matched_doc.metadata, "document_number", doc_num_hint),
                        "article": matched_chunk.article if matched_chunk else art_hint,
                        "clause": matched_chunk.clause if matched_chunk else cl_hint,
                        "required": True,
                        "verification_method": "content_store_multi_match",
                        "matching_document_count": match_count,
                        "reference_anchor_hash": anchor_hash,
                        "notes": f"Ambiguous: matched {match_count} documents",
                    })
                    all_snippets_verified = False
                    status_counts["ambiguous"] = status_counts.get("ambiguous", 0) + 1

                else:
                    case_labels.append({
                        "case_id": case_id,
                        "status": "document_not_found",
                        "document_id": None,
                        "document_number": doc_num_hint or None,
                        "article": art_hint or None,
                        "clause": cl_hint or None,
                        "required": True,
                        "verification_method": "content_store_search",
                        "matching_document_count": 0,
                        "reference_anchor_hash": anchor_hash,
                        "notes": f"Ground truth snippet not found in local corpus (hint: {doc_num_hint})",
                    })
                    all_snippets_verified = False
                    status_counts["document_not_found"] = status_counts.get("document_not_found", 0) + 1

            if q_type == "multi-hop" and all_snippets_verified and len(gt_contexts) > 1:
                multi_hop_all_covered += 1

        labels_sidecar.extend(case_labels)

    conn.close()

    # Save sidecar JSON
    sidecar_dir = Path("docs/evaluation/gold_labels")
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = sidecar_dir / "namsyntax_legal_qa_420_labels.json"
    with sidecar_path.open("w", encoding="utf-8") as f:
        json.dump(labels_sidecar, f, ensure_ascii=False, indent=2)
    print(f"Saved sidecar labels to {sidecar_path}")

    # Generate applicability report
    dups_count = sum(cnt - 1 for cnt in duplicate_questions.values() if cnt > 1)
    report_lines = []
    report_lines.append("# GOLDEN DATASET APPLICABILITY REPORT — namsyntax_legal_qa_420")
    report_lines.append("")
    report_lines.append("**Dataset**: `app/data/namsyntax_legal_qa_420.json`  ")
    report_lines.append(f"**Total Test Cases**: `{len(cases)}`  ")
    report_lines.append(f"**Sidecar Labels**: `{sidecar_path}`  ")
    report_lines.append("")

    report_lines.append("## 1. Dataset Breakdown by Question Type")
    report_lines.append("")
    report_lines.append("| Question Type | Count | Percentage |")
    report_lines.append("| :--- | ---: | ---: |")
    for qt, cnt in type_counts.items():
        report_lines.append(f"| `{qt}` | {cnt} | {cnt / len(cases) * 100:.1f}% |")
    report_lines.append("")

    report_lines.append("## 2. Deterministic Verification & Label Coverage")
    report_lines.append("")
    report_lines.append("| Label Status | Snippet Count | Description |")
    report_lines.append("| :--- | ---: | :--- |")
    for st, cnt in status_counts.items():
        report_lines.append(f"| `{st}` | {cnt} | Cases/snippets with status {st} |")
    report_lines.append("")

    report_lines.append("## 3. Detailed Verification Metrics")
    report_lines.append("")
    report_lines.append(f"- **Verified Document Labels**: `{verified_doc_count}`")
    report_lines.append(f"- **Verified Article Labels**: `{verified_art_count}`")
    report_lines.append(f"- **Verified Clause Labels**: `{verified_clause_count}`")
    report_lines.append(f"- **Multi-Hop All-Evidence Verified**: `{multi_hop_all_covered} / {multi_hop_total}`")
    report_lines.append(f"- **Duplicate Question Text**: `{dups_count}`")
    report_lines.append("")

    report_lines.append("## 4. Skip Reasons & Corpus Mismatch Notes")
    report_lines.append("")
    report_lines.append("- `unanswerable`: Unanswerable test cases explicitly have no assigned gold document.")
    report_lines.append("- `document_not_found`: Snippets whose full legal document was not indexed in the current local content store sample.")
    report_lines.append("- `ambiguous`: Snippets matching multiple legal documents.")
    report_lines.append("")

    report_path = Path("docs/evaluation/golden_dataset_applicability_report.md")
    with report_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"Saved applicability report to {report_path}")


if __name__ == "__main__":
    audit_golden_dataset()
