import sys
import os
import json
import re
from typing import Dict, List, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ingestion.schemas import LegalDocumentSchema, ProcessedLegalDocument, LegalASTNode
from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline
from app.ingestion.postprocessing.text_normalizer import TextNormalizer

def find_missing_segments(raw_text: str, reconstructed_text: str) -> List[Dict[str, Any]]:
    """
    Finds exact text segments present in raw_text that do not appear in reconstructed_text.
    """
    missing_segments = []
    # Split raw text into non-empty lines
    raw_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    recon_normalized = " ".join(reconstructed_text.split())

    search_pos = 0
    for line in raw_lines:
        line_clean = " ".join(line.split())
        if not line_clean:
            continue
        
        pos = raw_text.find(line, search_pos)
        if pos != -1:
            search_pos = pos + len(line)
        else:
            pos = raw_text.find(line)

        if line_clean not in recon_normalized:
            missing_segments.append({
                "start_pos": pos if pos != -1 else 0,
                "end_pos": (pos + len(line)) if pos != -1 else len(line),
                "text": line[:100] + ("..." if len(line) > 100 else ""),
                "full_line": line,
                "reason": "NOT_FOUND_IN_RECONSTRUCTION",
                "classification": "UNPARSED_OR_DROPPED"
            })

    return missing_segments

def audit_document(file_path: str, pipeline: LegalPreprocessingPipeline) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    doc_schema = LegalDocumentSchema(**raw_json)
    processed_doc = pipeline.process(doc_schema)

    raw_full_text = doc_schema.full_text or ""
    raw_html_text = doc_schema.html_text or ""

    # RAW metrics
    raw_chars = len(raw_full_text)
    raw_bytes = len(raw_full_text.encode("utf-8"))
    raw_html_chars = len(raw_html_text)

    # NORMALIZED metrics
    normalizer = TextNormalizer()
    text_blocks = normalizer.build_text_blocks(raw_full_text, raw_html_text, doc_schema.source)
    norm_chars = sum(len(b.normalized_text) for b in text_blocks)
    norm_blocks_count = len(text_blocks)

    # AST metrics
    ast_root = processed_doc.legal_structure
    ast_nodes_count = count_ast_nodes(ast_root)
    ast_text = get_ast_concatenated_text(ast_root)
    ast_chars = len(ast_text)

    # CHUNK metrics
    chunks = processed_doc.chunks
    chunk_chars = sum(len(c.text) for c in chunks)

    # 1. MISSING TEXT AUDIT
    missing_segments = find_missing_segments(raw_full_text, ast_text)
    missing_chars_count = sum(len(m["full_line"]) for m in missing_segments)

    # 2. DUPLICATION AUDIT
    duplicated_segments = find_duplicated_text(text_blocks, ast_root)

    # 3. ORDERING AUDIT
    ordering_violations = check_ordering_violations(text_blocks, ast_root)

    # 4. EMPTY NODE AUDIT
    empty_nodes = check_empty_nodes(ast_root)

    # 5. STRUCTURAL HALLUCINATION & FALSE POSITIVES AUDIT
    hallucinations = check_structural_hallucination(ast_root, raw_full_text)
    false_positives = check_false_positive_references(ast_root, raw_full_text)

    # 6. STRUCTURAL COVERAGE COUNTS
    node_counts = {
        "chapters": 0, "sections": 0, "articles": 0,
        "clauses": 0, "points": 0, "subpoints": 0,
        "appendices": 0, "signatures": 0, "unresolved": 0
    }
    collect_node_counts(ast_root, node_counts)

    # 7. METADATA AUDIT (All 9 fields)
    meta = processed_doc.metadata
    meta_fields = {
        "document_type": meta.document_type,
        "official_number": meta.official_number,
        "issued_date": meta.issued_date,
        "effective_date": meta.effective_date,
        "enforced_date": meta.enforced_date,
        "expiry_date": meta.expiry_date,
        "issuing_body": meta.issuing_body,
        "signer": meta.signer,
        "status": meta.status,
    }

    found_meta_count = sum(1 for field in meta_fields.values() if field.value and field.value != "UNKNOWN")
    unknown_meta_count = 9 - found_meta_count

    # 8. COVERAGE PERCENTAGE
    clean_raw_text = "\n".join([line.strip() for line in raw_full_text.splitlines() if line.strip()])
    clean_raw_len = len(clean_raw_text)
    ast_len = len(ast_text)
    
    if clean_raw_len > 0:
        coverage_pct = (min(ast_len, clean_raw_len) / clean_raw_len) * 100.0
    else:
        coverage_pct = 100.0

    # 9. QUALITY GATE EVALUATION
    if missing_chars_count > 0 or len(duplicated_segments) > 0 or len(ordering_violations) > 0 or len(hallucinations) > 0 or coverage_pct < 99.0:
        final_status = "FAIL"
        reason = f"Fails strict integrity check: missing_chars={missing_chars_count}, duplicates={len(duplicated_segments)}, ordering_violations={len(ordering_violations)}, hallucinations={len(hallucinations)}, coverage={coverage_pct:.2f}%"
    elif len(empty_nodes) > 0 or unknown_meta_count > 0:
        final_status = "PASS_WITH_WARNINGS"
        reason = f"Passes text integrity (coverage {coverage_pct:.2f}%), but has partial metadata ({found_meta_count}/9 found) or minor warnings."
    else:
        final_status = "PASS"
        reason = "Passes all strict quality gate criteria with 100% data integrity."

    return {
        "source": processed_doc.source,
        "source_id": processed_doc.source_id,
        "url": processed_doc.url,
        "title": processed_doc.title,
        "raw_chars": raw_chars,
        "raw_bytes": raw_bytes,
        "raw_html_chars": raw_html_chars,
        "norm_chars": norm_chars,
        "norm_blocks": norm_blocks_count,
        "ast_chars": ast_chars,
        "ast_nodes": ast_nodes_count,
        "chunk_chars": chunk_chars,
        "chunks_count": len(chunks),
        "coverage_pct": round(coverage_pct, 2),
        "missing_segments": missing_segments,
        "missing_chars": missing_chars_count,
        "duplicated_segments": duplicated_segments,
        "ordering_violations": ordering_violations,
        "empty_nodes": empty_nodes,
        "hallucinations": hallucinations,
        "false_positives": false_positives,
        "node_counts": node_counts,
        "metadata_fields": meta_fields,
        "found_meta_count": found_meta_count,
        "unknown_meta_count": unknown_meta_count,
        "final_status": final_status,
        "reason": reason
    }

def count_ast_nodes(node: LegalASTNode) -> int:
    cnt = 1
    for child in node.children:
        cnt += count_ast_nodes(child)
    return cnt

def get_ast_concatenated_text(node: LegalASTNode) -> str:
    texts = []
    if node.raw_text:
        texts.append(node.raw_text)
    for child in node.children:
        c_str = get_ast_concatenated_text(child)
        if c_str:
            texts.append(c_str)
    return "\n".join(texts)

def collect_node_counts(node: LegalASTNode, counts: Dict[str, int]):
    node_type_to_key = {
        "chapter": "chapters",
        "section": "sections",
        "article": "articles",
        "clause": "clauses",
        "point": "points",
        "subpoint": "subpoints",
        "appendix": "appendices",
        "signature": "signatures",
        "unresolved": "unresolved",
    }
    key = node_type_to_key.get(node.node_type)
    if key in counts:
        counts[key] += 1
    for child in node.children:
        collect_node_counts(child, counts)

def find_duplicated_text(blocks: List[Any], root: LegalASTNode) -> List[str]:
    duplicates = []
    seen_ids = set()
    
    def check_node(n: LegalASTNode):
        for bid in n.source_block_ids:
            if bid in seen_ids:
                duplicates.append(f"Block {bid} appended multiple times in AST")
            else:
                seen_ids.add(bid)
        for child in n.children:
            check_node(child)
            
    check_node(root)
    return duplicates

def check_ordering_violations(blocks: List[Any], root: LegalASTNode) -> List[str]:
    violations = []
    traversed_block_ids = []
    
    def collect_bids(n: LegalASTNode):
        for bid in n.source_block_ids:
            traversed_block_ids.append(bid)
        for child in n.children:
            collect_bids(child)

    collect_bids(root)
    
    # Extract order numbers from block_ids (e.g. full_000001/html_000001 -> 1)
    orders = []
    for bid in traversed_block_ids:
        m = re.search(r'(?:block|full|html)_(\d+)', bid)
        if m:
            orders.append(int(m.group(1)))

    for idx in range(len(orders) - 1):
        if orders[idx] > orders[idx+1]:
            violations.append(f"ORDERING_VIOLATION: block_{orders[idx]:06d} appears before block_{orders[idx+1]:06d}")

    return violations

def check_empty_nodes(root: LegalASTNode) -> List[str]:
    empty_nodes = []
    def inspect_node(n: LegalASTNode):
        if n.node_type in ["article", "clause", "point"] and not n.raw_text.strip() and not n.children:
            empty_nodes.append(f"EMPTY_NODE: {n.node_type} {n.number or ''} (node_id: {n.node_id}) text is empty")
        for child in n.children:
            inspect_node(child)
    inspect_node(root)
    return empty_nodes

def check_structural_hallucination(root: LegalASTNode, raw_text: str) -> List[str]:
    hallucinations = []
    def inspect_node(n: LegalASTNode):
        if n.node_type == "article" and n.number:
            target = f"Điều {n.number}"
            if target.lower() not in raw_text.lower():
                hallucinations.append(f"STRUCTURAL_HALLUCINATION: {target} not present in raw text")
        for child in n.children:
            inspect_node(child)
    inspect_node(root)
    return hallucinations

def check_false_positive_references(root: LegalASTNode, raw_text: str) -> List[str]:
    false_positives = []
    def inspect_node(n: LegalASTNode):
        if n.node_type in ["article", "clause", "point"]:
            text_low = n.normalized_text.lower()
            if "theo khoản" in text_low or "quy định tại điều" in text_low or "căn cứ điều" in text_low:
                if len(text_low) < 50 and ("theo" in text_low or "căn cứ" in text_low):
                    false_positives.append(f"FALSE_POSITIVE_REF: Node {n.node_id} ({n.node_type}) might be cross-reference string: '{n.normalized_text}'")
        for child in n.children:
            inspect_node(child)
    inspect_node(root)
    return false_positives

def print_audit_report(res: Dict[str, Any]):
    print("=" * 70)
    print("      LEGAL PREPROCESSING DATA INTEGRITY AUDIT REPORT")
    print("=" * 70)
    print(f"Document Title: {res['title']}")
    print(f"Source:         {res['source']}")
    print(f"Source ID:      {res['source_id']}")
    print(f"URL:            {res['url']}\n")

    print("RAW INPUT:")
    print(f"  Characters:   {res['raw_chars']:,}")
    print(f"  Bytes:        {res['raw_bytes']:,}")
    print(f"  HTML Chars:   {res['raw_html_chars']:,}\n")

    print("NORMALIZED REPRESENTATION:")
    print(f"  Characters:   {res['norm_chars']:,}")
    print(f"  Blocks:       {res['norm_blocks']}\n")

    print("AST PARSED STRUCTURE:")
    print(f"  Characters:   {res['ast_chars']:,}")
    print(f"  AST Nodes:    {res['ast_nodes']}\n")

    print("CHUNKS RECONSTRUCTION:")
    print(f"  Characters:   {res['chunk_chars']:,}")
    print(f"  Total Chunks: {res['chunks_count']}\n")

    print("-" * 70)
    print("1. TEXT INTEGRITY AUDIT")
    print("-" * 70)
    print(f"  Text Coverage:          {res['coverage_pct']}%")
    print(f"  Missing Characters:     {res['missing_chars']}")
    print(f"  Missing Segments Count: {len(res['missing_segments'])}")
    print(f"  Duplicated Segments:    {len(res['duplicated_segments'])}")
    print(f"  Ordering Violations:    {len(res['ordering_violations'])}")

    if res['missing_segments']:
        print("\n  --- MISSING TEXT SEGMENTS DETAILS ---")
        for idx, seg in enumerate(res['missing_segments'][:5], 1):
            print(f"  [{idx}] Position [{seg['start_pos']}:{seg['end_pos']}] | Classification: {seg['classification']}")
            print(f"      Text: \"{seg['text']}\"")
            print(f"      Reason: {seg['reason']}")

    print("\n" + "-" * 70)
    print("2. STRUCTURAL COVERAGE & NODES")
    print("-" * 70)
    nc = res['node_counts']
    print(f"  Chapters:    {nc['chapters']:<5} | Sections:   {nc['sections']:<5} | Articles:   {nc['articles']}")
    print(f"  Clauses:     {nc['clauses']:<5} | Points:     {nc['points']:<5} | Subpoints:  {nc['subpoints']}")
    print(f"  Appendices:  {nc['appendices']:<5} | Signatures: {nc['signatures']:<5} | Unresolved: {nc['unresolved']}")

    print("\n" + "-" * 70)
    print("3. METADATA AUDIT (Completion: {}/9)".format(res['found_meta_count']))
    print("-" * 70)
    for name, f in res['metadata_fields'].items():
        status_str = "FOUND" if (f.value and f.value != "UNKNOWN") else "UNKNOWN"
        val_str = f.value if f.value else "UNKNOWN"
        print(f"  {name:<16} -> Status: {status_str:<7} | Value: {val_str:<22} | Source: {f.source:<15} | Conf: {f.confidence}")

    print("\n" + "-" * 70)
    print("4. ERRORS & ANOMALIES")
    print("-" * 70)
    print(f"  Empty Nodes:               {len(res['empty_nodes'])}")
    print(f"  Structural Hallucinations: {len(res['hallucinations'])}")
    print(f"  False Positive References: {len(res['false_positives'])}")

    print("\n" + "=" * 70)
    print(f"FINAL AUDIT STATUS: {res['final_status']}")
    print(f"Reason: {res['reason']}")
    print("=" * 70 + "\n")

def main():
    pipeline = LegalPreprocessingPipeline()
    sample_dir = os.path.join(os.path.dirname(__file__), "..", "data", "scrapling_raw", "trial_samples")

    samples = [
        ("VBPL", "vbpl_sample.json"),
        ("VietLaw", "vietlaw_sample.json"),
        ("MOJ", "moj_sample.json")
    ]

    print("\n\n" + "#" * 70)
    print("  STRICT DATA INTEGRITY AUDIT FOR VIETNAMESE LEGAL PREPROCESSING")
    print("#" * 70 + "\n")

    audit_results = []

    for src_name, filename in samples:
        file_path = os.path.join(sample_dir, filename)
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue

        res = audit_document(file_path, pipeline)
        audit_results.append(res)
        print_audit_report(res)

if __name__ == "__main__":
    main()
