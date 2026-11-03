"""Conservative deterministic help for two unambiguous request shapes.

Unknown topics continue through retrieval; this is not a general topic classifier.
"""
import re

from app.services.legal_topic_terms import extract_official_topic_phrases, fold_topic_text


def deterministic_guidance(query: str) -> tuple[str, str] | None:
    folded = fold_topic_text(query)
    topics = extract_official_topic_phrases(query, limit=8)
    transaction = re.search(r'\b(?:hop dong|dat coc|tien coc|vay|muon|luong|mua|ban|thanh toan|thue|thua ke|boi thuong)\b', folded)
    if 'giu tien' in folded and not topics and not transaction:
        return ('clarification',
                'Tôi chưa đủ dữ kiện và không thể khẳng định chắc thắng. '
                'Khoản tiền phát sinh từ giao dịch hoặc thỏa thuận nào? '
                'Bạn có chứng từ chuyển tiền, tin nhắn hoặc giấy tờ gì? '
                'Thời điểm giao tiền, hạn trả và yêu cầu hoàn trả là khi nào?')
    legal_signal = bool(topics) or re.search(
        r'\b(?:luat|phap ly|quyen|nghia vu|hop dong|kien|phat|vi pham|trach nhiem|'
        r'giay phep|dang ky|nhan hieu|ban quyen|kinh doanh|de ban|boi thuong|an toan|'
        r'tranh chap|bao hiem|thue|thu tuc)\b|\d+/\d{4}/', folded)
    # Positive recipe/astronomy requests only; never reject an unknown legal term
    # merely because it is missing from the curated topic dictionary.
    # Every requested clause must fit a known nonlegal request in full.
    # A recipe phrase followed by an unknown/fraud/legal clause must continue.
    clauses = [part.strip(' .!') for part in re.split(r'\s+va\s+|[;?!]+', folded)
               if part.strip(' .!')]
    clauses = [re.sub(r'^vl-audit-\d{8}:\s*', '', part) for part in clauses]
    clearly_nonlegal = bool(clauses) and all(
        re.fullmatch(r'(?:cach|huong dan)(?: toi)?(?: cach)? lam banh(?: mi)? chuoi', part)
        or re.fullmatch(r'(?:giai thich )?vi sao sao hoa co mau do', part)
        for part in clauses
    )
    if clearly_nonlegal and not legal_signal:
        return ('unsupported_intent',
                'VietLex hỗ trợ tra cứu và nghiên cứu pháp luật. '
                'Yêu cầu nấu ăn hoặc giải thích thiên văn này nằm ngoài phạm vi; '
                'bạn có thể gửi một câu hỏi pháp luật cụ thể.')
    return None
