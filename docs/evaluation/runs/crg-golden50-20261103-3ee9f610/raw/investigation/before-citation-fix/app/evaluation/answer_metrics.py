from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from app.evaluation.legal_citations import LegalCitation, parse_legal_citations


ANSWER_QUALITY_SKIP_STATUSES = {
    "input_guardrail_error",
    "output_guardrail_error",
    "retrieval_error",
    "reranker_error",
    "generation_error",
}

ANSWER_METRIC_VERSION = "3.1.0"


def _entity_mentions(text: str, expected: list[str]) -> list[str]:
    """Lexical mentions, not NER or proof of a claim about an entity.

    Gold names can include lowercase words (Bộ Tài chính). Match those whole
    labels first; retain other capitalized names to count extra mentions.
    """
    text = unicodedata.normalize("NFC", text)
    matched = []
    mentions = []
    for entity in expected:
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in entity.split()) + r"(?!\w)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched.append(match.span())
            mentions.append(entity)
    unmatched = text
    for left, right in sorted(matched, reverse=True):
        unmatched = unmatched[:left] + " " * (right - left) + unmatched[right:]
    words = list(re.finditer(r"[^\W\d_]+", unmatched))
    index = 0
    while index < len(words):
        word = words[index]
        if not word.group()[0].isupper():
            index += 1
            continue
        start, end = word.span()
        index += 1
        while (index < len(words) and words[index].group()[0].isupper()
               and text[end:words[index].start()].isspace()):
            end = words[index].end()
            index += 1
        mentions.append(" ".join(text[start:end].split()))
    return mentions

ANSWER_CASE_METRIC_KEYS = (
    "exact_match",
    "token_precision",
    "token_recall",
    "token_f1",
    "char_f1",
    "rouge_l",
    "chrf",
    "number_precision",
    "number_recall",
    "date_precision",
    "date_recall",
    "entity_precision",
    "entity_recall",
    "citation_precision",
    "citation_recall",
    "citation_coverage",
    "invalid_citation_rate",
)


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

    no_evidence_fallback = (
        "không tìm thấy bằng chứng pháp luật đủ tin cậy" in resp_lower
    )
    has_refusal_phrase = no_evidence_fallback or any(
        phrase in resp_lower for phrase in REFUSAL_PHRASES
    )
    has_disclaimer = any(phrase in resp_lower for phrase in DISCLAIMER_PHRASES)

    # Detect legal citations or factual assertions (e.g. "Điều X", "Khoản Y", "Luật Z")
    citations = re.findall(r"\b(Điều|Khoản|Chương|Mục|Luật|Nghị định|Thông tư)\s+\d+", clean_resp, re.IGNORECASE)
    words = clean_resp.split()

    if has_refusal_phrase:
        if len(citations) >= 1 or len(words) > 50:
            # Answer contains factual claims or citations alongside refusal phrase
            return "mixed_claim_refusal", False
        if not retrieved_contexts or no_evidence_fallback:
            return "no_evidence", True
        else:
            # Pure short refusal
            return "pure_refusal", True

    if not retrieved_contexts:
        # Missing evidence describes retrieval state, not an answer refusal.
        return "no_evidence", False

    if has_disclaimer:
        return "disclaimer", False

    return "normal_answer", False


def extract_entities_dates_numbers(text: str) -> Dict[str, List[str]]:
    """Extract numbers, dates, and legal entity names from text."""
    date_pattern = (
        r"\b\d{1,2}/\d{1,2}/\d{4}\b|"
        r"\bngày\s+\d+\s+tháng\s+\d+\s+năm\s+\d{4}\b"
    )
    dates = re.findall(date_pattern, text, re.IGNORECASE)
    text_without_dates = re.sub(date_pattern, " ", text, flags=re.IGNORECASE)
    numbers = re.findall(r"\b\d+(?:[\.,]\d+)?\b", text_without_dates)
    entities = _entity_mentions(text, [])
    return {
        "numbers": numbers,
        "dates": dates,
        "entities": entities
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


def _citation_satisfies(
    candidate: LegalCitation,
    requirement: LegalCitation,
) -> bool:
    """Return whether candidate contains every locator present in requirement."""
    return all(
        not expected or actual.casefold() == expected.casefold()
        for actual, expected in (
            (candidate.document_number, requirement.document_number),
            (candidate.article, requirement.article),
            (candidate.clause, requirement.clause),
        )
    )


def _parsed_citation_set(text: str) -> set[LegalCitation]:
    return set(parse_legal_citations(text))


def calculate_case_answer_metrics(
    pred_response: str,
    ref_answer: str,
    question_type: str,
    retrieved_contexts: List[str],
    expected_numbers: List[str] = None,
    expected_dates: List[str] = None,
    expected_entities: List[str] = None,
    *,
    status: str = "ok",
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
    entity_labels = [" ".join(unicodedata.normalize("NFC", value).split())
                     for value in (expected_entities or []) if value.strip()]
    ent_p, ent_r = calculate_pattern_precision_recall(
        _entity_mentions(pred_response, entity_labels), entity_labels
    )

    # Legal citation metrics
    pred_cites = _parsed_citation_set(pred_response)
    ref_cites = _parsed_citation_set(ref_answer)
    evidence_cites: set[LegalCitation] = set()
    for context in retrieved_contexts:
        evidence_cites.update(parse_legal_citations(context))

    supported_pred_cites = {
        citation
        for citation in pred_cites
        if any(
            _citation_satisfies(evidence, citation)
            for evidence in evidence_cites
        )
    }
    if evidence_cites:
        cite_prec = (
            round(len(supported_pred_cites) / len(pred_cites), 4)
            if pred_cites
            else 0.0
        )
        invalid_cite_rate = (
            round(
                len(pred_cites - supported_pred_cites) / len(pred_cites),
                4,
            )
            if pred_cites
            else 0.0
        )
    else:
        cite_prec = None
        invalid_cite_rate = None

    if ref_cites:
        covered_reference_cites = {
            citation
            for citation in ref_cites
            if any(
                _citation_satisfies(predicted, citation)
                for predicted in pred_cites
            )
        }
        cite_rec = round(
            len(covered_reference_cites) / len(ref_cites),
            4,
        )
        cite_cov = cite_rec
    else:
        cite_rec, cite_cov = None, None

    metric_skip_reasons: Dict[str, str] = {}
    for name, plural, expected in (
        ("number", "numbers", expected_numbers),
        ("date", "dates", expected_dates),
        ("entity", "entities", expected_entities),
    ):
        if not expected:
            reason = f"no_expected_{plural}"
            metric_skip_reasons[f"{name}_precision"] = reason
            metric_skip_reasons[f"{name}_recall"] = reason
    if not evidence_cites:
        metric_skip_reasons["citation_precision"] = (
            "no_retrieved_evidence_citations"
        )
        metric_skip_reasons["invalid_citation_rate"] = (
            "no_retrieved_evidence_citations"
        )
    if not ref_cites:
        metric_skip_reasons["citation_recall"] = "no_reference_citations"
        metric_skip_reasons["citation_coverage"] = "no_reference_citations"

    return {
        "applicable": status not in ANSWER_QUALITY_SKIP_STATUSES,
        "answer_metric_version": ANSWER_METRIC_VERSION,
        "skip_reason": (
            status if status in ANSWER_QUALITY_SKIP_STATUSES else None
        ),
        "refusal_category": category,
        "is_refusal": is_refusal,
        "metric_skip_reasons": metric_skip_reasons,
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

    def applicable(case: Dict[str, Any]) -> bool:
        metrics = case.get("metrics", {})
        if "applicable" in metrics:
            return bool(metrics["applicable"])
        return case.get("status", "ok") not in ANSWER_QUALITY_SKIP_STATUSES

    scored = [case for case in case_results if applicable(case)]
    skipped = [case for case in case_results if not applicable(case)]
    skip_reason_counts: Counter[str] = Counter(
        case.get("metrics", {}).get("skip_reason")
        or case.get("status")
        or "unspecified_skip_reason"
        for case in skipped
    )
    answerable = [c for c in scored if c.get("answerable", True)]
    unanswerable = [c for c in scored if not c.get("answerable", False)]

    # Refusal stats
    def refusal_category(case: Dict[str, Any]) -> str:
        return (
            case.get("refusal_category")
            or case.get("metrics", {}).get("refusal_category")
            or "normal_answer"
        )

    def is_refusal(case: Dict[str, Any]) -> bool:
        metrics = case.get("metrics", {})
        if "is_refusal" in metrics:
            return bool(metrics["is_refusal"])
        if "is_refusal" in case:
            return bool(case["is_refusal"])
        # A pure refusal category is unambiguous; no_evidence alone is not.
        return refusal_category(case) == "pure_refusal"

    categories = Counter(refusal_category(c) for c in scored)
    correct_unanswerable_refusals = sum(
        1
        for c in unanswerable
        if refusal_category(c) in ("pure_refusal", "no_evidence")
        and is_refusal(c)
    )
    all_refusals = sum(1 for c in scored if is_refusal(c))

    refusal_precision = (correct_unanswerable_refusals / all_refusals) if all_refusals else None
    refusal_recall = (correct_unanswerable_refusals / len(unanswerable)) if unanswerable else None
    unanswerable_accuracy = (correct_unanswerable_refusals / len(unanswerable)) if unanswerable else None

    # Answer similarity pass rate (token_f1 >= 0.5)
    answerable_correct = sum(
        1 for c in answerable if c.get("metrics", {}).get("token_f1", 0.0) >= 0.5
    )
    answer_similarity_pass_rate = (answerable_correct / len(answerable)) if answerable else None

    def case_skip_reason(case: Dict[str, Any], key: str | None = None) -> str:
        metrics = case.get("metrics", {})
        if not applicable(case):
            return (
                metrics.get("skip_reason")
                or case.get("status")
                or "unspecified_skip_reason"
            )
        if key is None:
            return "not_applicable_to_metric"
        if key not in metrics:
            return "metric_missing"
        return (metrics.get("metric_skip_reasons") or {}).get(
            key, "metric_unavailable"
        )

    def metric_detail(
        *,
        value: Optional[float],
        numerator: float,
        denominator: int,
        scored_count: int,
        skip_reasons: Counter[str],
        aggregation: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "value": value,
            "numerator": round(numerator, 6),
            "denominator": denominator,
            "coverage": round(scored_count / total, 4) if total else 0.0,
            "scored_cases": scored_count,
            "skipped_cases": total - scored_count,
            "skip_reasons": dict(sorted(skip_reasons.items())),
            "aggregation": aggregation,
            "reason": reason,
        }

    metric_details: Dict[str, Dict[str, Any]] = {}
    for key in ANSWER_CASE_METRIC_KEYS:
        values: List[float] = []
        reasons: Counter[str] = Counter()
        for case in case_results:
            metrics = case.get("metrics", {})
            if not applicable(case):
                reasons[case_skip_reason(case, key)] += 1
                continue
            if key not in metrics:
                reasons["metric_missing"] += 1
                continue
            value = metrics[key]
            if value is None:
                reasons[case_skip_reason(case, key)] += 1
                continue
            values.append(float(value))
        numerator = sum(values)
        denominator = len(values)
        metric_details[key] = metric_detail(
            value=round(numerator / denominator, 4) if denominator else None,
            numerator=numerator,
            denominator=denominator,
            scored_count=denominator,
            skip_reasons=reasons,
            aggregation="macro_case_mean",
            reason=(
                None
                if denominator
                else "no_cases"
                if not total
                else "no_applicable_values"
            ),
        )

    def case_rate_detail(
        *,
        numerator: int,
        eligible: List[Dict[str, Any]],
        denominator_reason: str,
        excluded_reason: str,
        aggregation: str = "case_count_ratio",
    ) -> Dict[str, Any]:
        reasons: Counter[str] = Counter(skip_reason_counts)
        eligible_ids = {id(case) for case in eligible}
        for case in scored:
            if id(case) not in eligible_ids:
                reasons[excluded_reason] += 1
        denominator = len(eligible)
        return metric_detail(
            value=round(numerator / denominator, 4) if denominator else None,
            numerator=numerator,
            denominator=denominator,
            scored_count=denominator,
            skip_reasons=reasons,
            aggregation=aggregation,
            reason=(
                None
                if denominator
                else "no_cases"
                if not total
                else denominator_reason
            ),
        )

    predicted_refusals = [case for case in scored if is_refusal(case)]
    metric_details["answer_similarity_pass_rate"] = case_rate_detail(
        numerator=answerable_correct,
        eligible=answerable,
        denominator_reason="no_answerable_cases",
        excluded_reason="unanswerable_case",
    )
    metric_details["unanswerable_accuracy"] = case_rate_detail(
        numerator=correct_unanswerable_refusals,
        eligible=unanswerable,
        denominator_reason="no_unanswerable_cases",
        excluded_reason="answerable_case",
    )
    metric_details["refusal_precision"] = case_rate_detail(
        numerator=correct_unanswerable_refusals,
        eligible=predicted_refusals,
        denominator_reason="no_predicted_refusals",
        excluded_reason="not_predicted_refusal",
    )
    metric_details["refusal_recall"] = case_rate_detail(
        numerator=correct_unanswerable_refusals,
        eligible=unanswerable,
        denominator_reason="no_unanswerable_cases",
        excluded_reason="answerable_case",
    )
    metric_details["mixed_claim_refusal_rate"] = case_rate_detail(
        numerator=categories["mixed_claim_refusal"],
        eligible=scored,
        denominator_reason="no_scored_cases",
        excluded_reason="not_applicable_to_metric",
    )

    return {
        "total_cases": total,
        "scored_cases": len(scored),
        "skipped_cases": len(skipped),
        "skip_reason_counts": dict(skip_reason_counts),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "refusal_categories_breakdown": dict(categories),
        "mixed_claim_refusal_rate": (
            round(categories["mixed_claim_refusal"] / len(scored), 4)
            if scored
            else None
        ),
        "metric_details": metric_details,
        "refusal_precision": round(refusal_precision, 4) if refusal_precision is not None else None,
        "refusal_recall": round(refusal_recall, 4) if refusal_recall is not None else None,
        "unanswerable_accuracy": round(unanswerable_accuracy, 4) if unanswerable_accuracy is not None else None,
        "answer_similarity_pass_rate": round(answer_similarity_pass_rate, 4) if answer_similarity_pass_rate is not None else None,
        **{
            key: metric_details[key]["value"]
            for key in ANSWER_CASE_METRIC_KEYS
        },
    }
