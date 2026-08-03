from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Set, Tuple


def normalize_text_for_metrics(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def token_level_metrics(pred: str, ref: str) -> Tuple[float, float, float]:
    """Calculate token precision, recall, and F1 score."""
    pred_tokens = normalize_text_for_metrics(pred).split()
    ref_tokens = normalize_text_for_metrics(ref).split()
    if not pred_tokens or not ref_tokens:
        if not pred_tokens and not ref_tokens:
            return 1.0, 1.0, 1.0
        return 0.0, 0.0, 0.0

    pred_counter = Counter(pred_tokens)
    ref_counter = Counter(ref_tokens)
    common = sum((pred_counter & ref_counter).values())

    precision = common / len(pred_tokens)
    recall = common / len(ref_tokens)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def char_f1_metric(pred: str, ref: str, n: int = 3) -> float:
    """Calculate character n-gram F1 score."""
    p_clean = " ".join(normalize_text_for_metrics(pred).split())
    r_clean = " ".join(normalize_text_for_metrics(ref).split())
    if not p_clean or not r_clean:
        return 1.0 if p_clean == r_clean else 0.0

    def get_char_ngrams(text: str, n: int) -> Counter:
        return Counter([text[i:i+n] for i in range(len(text) - n + 1)])

    p_ngrams = get_char_ngrams(p_clean, n)
    r_ngrams = get_char_ngrams(r_clean, n)
    common = sum((p_ngrams & r_ngrams).values())
    p_len = sum(p_ngrams.values())
    r_len = sum(r_ngrams.values())
    if p_len == 0 or r_len == 0:
        return 0.0
    prec = common / p_len
    rec = common / r_len
    return round((2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0, 4)


def lcs_length(x: List[str], y: List[str]) -> int:
    """Length of Longest Common Subsequence."""
    m, n = len(x), len(y)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if x[i] == y[j]:
                dp[i+1][j+1] = dp[i][j] + 1
            else:
                dp[i+1][j+1] = max(dp[i+1][j], dp[i][j+1])
    return dp[m][n]


def rouge_l_metric(pred: str, ref: str) -> float:
    """Calculate ROUGE-L score based on word LCS."""
    p_tokens = normalize_text_for_metrics(pred).split()
    r_tokens = normalize_text_for_metrics(ref).split()
    if not p_tokens or not r_tokens:
        return 1.0 if p_tokens == r_tokens else 0.0
    lcs = lcs_length(p_tokens, r_tokens)
    prec = lcs / len(p_tokens)
    rec = lcs / len(r_tokens)
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return round(f1, 4)


def chrf_metric(pred: str, ref: str, min_n: int = 1, max_n: int = 6, beta: float = 2.0) -> float:
    """Calculate CHRF score."""
    p_clean = normalize_text_for_metrics(pred).replace(" ", "")
    r_clean = normalize_text_for_metrics(ref).replace(" ", "")
    if not p_clean or not r_clean:
        return 1.0 if p_clean == r_clean else 0.0

    prec_sum = 0.0
    rec_sum = 0.0
    count = 0
    for n in range(min_n, max_n + 1):
        if len(p_clean) < n or len(r_clean) < n:
            continue
        p_ngrams = Counter([p_clean[i:i+n] for i in range(len(p_clean) - n + 1)])
        r_ngrams = Counter([r_clean[i:i+n] for i in range(len(r_clean) - n + 1)])
        common = sum((p_ngrams & r_ngrams).values())
        p_len = sum(p_ngrams.values())
        r_len = sum(r_ngrams.values())
        prec_sum += (common / p_len) if p_len > 0 else 0.0
        rec_sum += (common / r_len) if r_len > 0 else 0.0
        count += 1

    if count == 0:
        return 0.0
    avg_prec = prec_sum / count
    avg_rec = rec_sum / count
    if avg_prec == 0 and avg_rec == 0:
        return 0.0
    beta_sq = beta ** 2
    score = (1 + beta_sq) * (avg_prec * avg_rec) / (beta_sq * avg_prec + avg_rec)
    return round(score, 4)


REFUSAL_PHRASES = [
    "không biết",
    "không có thông tin",
    "chưa có dữ liệu",
    "không tìm thấy",
    "không đủ dữ liệu",
    "tài liệu không đề cập",
    "xin lỗi",
    "không thể cung cấp",
    "không được quy định",
]

DISCLAIMER_PHRASES = [
    "chỉ nhằm cung cấp thông tin",
    "không phải tư vấn pháp lý",
    "kiểm tra lại trên nguồn chính thức",
    "người có chuyên môn",
]

ERROR_SIGNATURES = [
    "hệ thống chưa thể xử lý",
    "đã xảy ra lỗi",
    "guardrail error",
    "timeout",
    "http 429",
    "api keys đang bị giới hạn",
]


def classify_response_refusal(
    response: str,
    retrieved_contexts: List[str]
) -> Tuple[str, bool]:
    """
    Deterministic refusal classifier distinguishing:
    - pure_refusal: no claims, short text, refusal phrase present
    - disclaimer: normal answer with legal disclaimer
    - mixed_claim_refusal: factual claims + refusal phrase
    - technical_error: system error text
    - no_evidence: empty context or fallback response
    - normal_answer: grounded answer without refusal
    
    Returns (category, is_refusal_flag).
    """
    clean_resp = response.strip()
    resp_lower = clean_resp.casefold()

    if any(sig in resp_lower for sig in ERROR_SIGNATURES):
        return "technical_error", False

    if not retrieved_contexts or "không tìm thấy bằng chứng pháp luật đủ tin cậy" in resp_lower:
        return "no_evidence", True

    has_refusal_phrase = any(phrase in resp_lower for phrase in REFUSAL_PHRASES)
    has_disclaimer = any(phrase in resp_lower for phrase in DISCLAIMER_PHRASES)

    # Detect legal citations or factual assertions (e.g. "Điều X", "Khoản Y", "Luật Z")
    citations = re.findall(r"\b(Điều|Khoản|Chương|Mục|Luật|Nghị định|Thông tư)\s+\d+", clean_resp, re.IGNORECASE)
    words = clean_resp.split()

    if has_refusal_phrase:
        if len(citations) >= 1 or len(words) > 50:
            # Answer contains factual claims or citations alongside refusal phrase
            return "mixed_claim_refusal", False
        else:
            # Pure short refusal
            return "pure_refusal", True

    if has_disclaimer:
        return "disclaimer", False

    return "normal_answer", False


def extract_entities_dates_numbers(text: str) -> Dict[str, List[str]]:
    """Extract numbers, dates, and legal entity names from text."""
    numbers = re.findall(r"\b\d+(?:[\.,]\d+)?\b", text)
    dates = re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\bngày\s+\d+\s+tháng\s+\d+\s+năm\s+\d{4}\b", text, re.IGNORECASE)
    entities = re.findall(r"\b[A-ZĐ][a-zđ]+(?:\s+[A-ZĐ][a-zđ]+)*\b", text)
    return {
        "numbers": numbers,
        "dates": dates,
        "entities": [e for e in entities if len(e) > 3]
    }


def calculate_pattern_precision_recall(pred_items: List[str], ref_items: List[str]) -> Tuple[Optional[float], Optional[float]]:
    if not ref_items:
        return None, None
    if not pred_items:
        return 0.0, 0.0

    pred_set = set(item.casefold() for item in pred_items)
    ref_set = set(item.casefold() for item in ref_items)
    common = len(pred_set & ref_set)
    prec = common / len(pred_set) if pred_set else 0.0
    rec = common / len(ref_set) if ref_set else 0.0
    return round(prec, 4), round(rec, 4)


def extract_legal_citations(text: str) -> Set[str]:
    """Extract citations formatted like 'Điều 3 Luật 72/2020/QH14' or 'Điều 5'."""
    pattern = r"\b(?:Điều|Khoản|Chương)\s+\d+[A-Za-z]?(?:\s+Luật\s+\d{1,4}/\d{4}/[A-ZĐ0-9-]+)?"
    matches = re.findall(pattern, text, re.IGNORECASE)
    return set(" ".join(m.casefold().split()) for m in matches)


def calculate_case_answer_metrics(
    pred_response: str,
    ref_answer: str,
    question_type: str,
    retrieved_contexts: List[str],
    expected_numbers: List[str] = None,
    expected_dates: List[str] = None,
    expected_entities: List[str] = None,
) -> Dict[str, Any]:
    """Calculate all deterministic answer metrics for a single response."""
    category, is_refusal = classify_response_refusal(pred_response, retrieved_contexts)

    # Exact Match
    norm_pred = normalize_text_for_metrics(pred_response)
    norm_ref = normalize_text_for_metrics(ref_answer)
    exact_match = 1.0 if norm_pred == norm_ref else 0.0

    # Token & Char metrics
    tok_prec, tok_rec, tok_f1 = token_level_metrics(pred_response, ref_answer)
    char_f1 = char_f1_metric(pred_response, ref_answer)
    rouge_l = rouge_l_metric(pred_response, ref_answer)
    chrf = chrf_metric(pred_response, ref_answer)

    # Number / Date / Entity metrics
    extracted = extract_entities_dates_numbers(pred_response)
    num_p, num_r = calculate_pattern_precision_recall(extracted["numbers"], expected_numbers or [])
    date_p, date_r = calculate_pattern_precision_recall(extracted["dates"], expected_dates or [])
    ent_p, ent_r = calculate_pattern_precision_recall(extracted["entities"], expected_entities or [])

    # Legal citation metrics
    pred_cites = extract_legal_citations(pred_response)
    ref_cites = extract_legal_citations(ref_answer)
    if ref_cites:
        common_cites = len(pred_cites & ref_cites)
        cite_prec = round(common_cites / len(pred_cites), 4) if pred_cites else 0.0
        cite_rec = round(common_cites / len(ref_cites), 4)
        cite_cov = round(common_cites / len(ref_cites), 4)
        invalid_cites = len(pred_cites - ref_cites)
        invalid_cite_rate = round(invalid_cites / len(pred_cites), 4) if pred_cites else 0.0
    else:
        cite_prec, cite_rec, cite_cov, invalid_cite_rate = None, None, None, None

    return {
        "refusal_category": category,
        "is_refusal": is_refusal,
        "exact_match": exact_match,
        "token_precision": tok_prec,
        "token_recall": tok_rec,
        "token_f1": tok_f1,
        "char_f1": char_f1,
        "rouge_l": rouge_l,
        "chrf": chrf,
        "number_precision": num_p,
        "number_recall": num_r,
        "date_precision": date_p,
        "date_recall": date_r,
        "entity_precision": ent_p,
        "entity_recall": ent_r,
        "citation_precision": cite_prec,
        "citation_recall": cite_rec,
        "citation_coverage": cite_cov,
        "invalid_citation_rate": invalid_cite_rate,
    }


def aggregate_answer_metrics(case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate answer metrics across all test cases."""
    total = len(case_results)
    if total == 0:
        return {}

    answerable = [c for c in case_results if c.get("answerable", True)]
    unanswerable = [c for c in case_results if not c.get("answerable", False)]

    # Refusal stats
    categories = Counter(c.get("refusal_category", "normal_answer") for c in case_results)
    correct_unanswerable_refusals = sum(
        1 for c in unanswerable if c.get("refusal_category") in ("pure_refusal", "no_evidence")
    )
    all_refusals = sum(1 for c in case_results if c.get("is_refusal"))

    refusal_precision = (correct_unanswerable_refusals / all_refusals) if all_refusals else None
    refusal_recall = (correct_unanswerable_refusals / len(unanswerable)) if unanswerable else None
    unanswerable_accuracy = (correct_unanswerable_refusals / len(unanswerable)) if unanswerable else None

    # Answer similarity pass rate (token_f1 >= 0.5)
    answerable_correct = sum(
        1 for c in answerable if c.get("metrics", {}).get("token_f1", 0.0) >= 0.5
    )
    answer_similarity_pass_rate = (answerable_correct / len(answerable)) if answerable else None

    def avg_metric(key: str) -> Optional[float]:
        vals = [c["metrics"][key] for c in case_results if "metrics" in c and key in c["metrics"] and c["metrics"][key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "total_cases": total,
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "refusal_categories_breakdown": dict(categories),
        "mixed_claim_refusal_rate": round(categories["mixed_claim_refusal"] / total, 4),
        "refusal_precision": round(refusal_precision, 4) if refusal_precision is not None else None,
        "refusal_recall": round(refusal_recall, 4) if refusal_recall is not None else None,
        "unanswerable_accuracy": round(unanswerable_accuracy, 4) if unanswerable_accuracy is not None else None,
        "answer_similarity_pass_rate": round(answer_similarity_pass_rate, 4) if answer_similarity_pass_rate is not None else None,
        "exact_match": avg_metric("exact_match"),
        "token_precision": avg_metric("token_precision"),
        "token_recall": avg_metric("token_recall"),
        "token_f1": avg_metric("token_f1"),
        "char_f1": avg_metric("char_f1"),
        "rouge_l": avg_metric("rouge_l"),
        "chrf": avg_metric("chrf"),
        "citation_precision": avg_metric("citation_precision"),
        "citation_recall": avg_metric("citation_recall"),
        "invalid_citation_rate": avg_metric("invalid_citation_rate"),
    }

