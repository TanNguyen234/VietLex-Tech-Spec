"""Conservative deterministic help for unambiguous non-retrieval request shapes.

Unknown legal topics continue through retrieval; this is not a general topic classifier.
"""

import re

from app.services.legal_topic_terms import extract_official_topic_phrases, fold_topic_text

_TRANSACTION_PATTERN = re.compile(
    r'\b(?:hop dong|dat coc|tien coc|vay|muon|luong|mua|ban|thanh toan|thue|thua ke|boi thuong)\b'
)

_LEGAL_SIGNAL_PATTERN = re.compile(
    r'\b(?:luat|phap ly|phap luat|quyen|nghia vu|hop dong|kien|khoi kien|phat|xu phat|'
    r'vi pham|trach nhiem|giay phep|dang ky|nhan hieu|ban quyen|kinh doanh|de ban|'
    r'boi thuong|an toan|tranh chap|bao hiem|thue|thu tuc|toa an|dieu|khoan|'
    r'nghi dinh|thong tu|bo luat|hinh su|dan su|lao dong|dat dai|hon nhan|ly hon|'
    r'thua ke|to cao|khieu nai|tai san|cong chung|doanh nghiep|bhxh)\b|\d+/\d{4}/'
)

_GREETING_PATTERN = re.compile(
    r'(?:(?:xin )?chao|hello|hi|hey|alo|aloha|good morning|good afternoon|good evening)'
    r'(?:\s+(?:vietlex|ban|cau|em|anh|chi|ad|admin|bot|tro ly|he thong|moi nguoi|there|all|everyone|oi|a|nhe|nha|nhi)){0,4}'
    r'|chao buoi (?:sang|trua|chieu|toi)'
    r'|co ai(?: o do)? khong'
)

_THANKS_OR_FAREWELL_PATTERN = re.compile(
    r'(?:(?:da |xin )?cam on|thank(?:s| you)?|tks|tam biet|bye|goodbye|see you|hen gap lai)'
    r'(?:\s+(?:vietlex|ban|ad|admin|bot|nhieu|rat nhieu|nhe|nha|a)){0,4}'
)

_META_ASSISTANT_PATTERN = re.compile(
    r'(?:ban la ai|ban ten(?: la)? gi|ai tao ra ban|vietlex la gi|vietlex lam duoc gi|'
    r'he thong nay la gi|ban(?: co the)? lam(?: duoc)? gi|ban giup(?: duoc)? gi|'
    r'tro ly nay la gi|huong dan su dung(?: vietlex)?)'
)

_RECIPE_OR_ASTRONOMY_PATTERN = re.compile(
    r'(?:cach|huong dan)(?: toi)?(?: cach)? lam banh(?: mi)? chuoi'
    r'|(?:giai thich )?vi sao sao hoa co mau do'
)

_CHITCHAT_SMALLTALK_PATTERN = re.compile(
    r'(?:hom nay )?thoi tiet(?: hom nay)?(?: o [a-z0-9 ]{1,30})? (?:the nao|ra sao|bao nhieu do|co mua khong)'
    r'|(?:bay gio la )?may gio(?: roi)?'
    r'|hom nay(?: la)? (?:thu may|ngay bao nhieu)'
    r'|(?:ke|doc|hat)(?: cho toi)?(?: mot)? (?:cau chuyen cuoi|truyen cuoi|bai tho|bai hat)'
    r'|ban khoe khong|khoe khong'
)

_GREETING_RESPONSE = (
    'Xin chào! Tôi là VietLex — trợ lý tra cứu và nghiên cứu pháp luật Việt Nam '
    '(hỗ trợ tìm quy định, đối chiếu điều khoản và kiểm chứng nguồn dẫn chiếu). '
    'Bạn hãy nhập câu hỏi pháp luật cụ thể để tôi tra cứu giúp bạn.'
)

_THANKS_RESPONSE = (
    'Rất vui được hỗ trợ bạn! Khi nào cần tra cứu quy định pháp luật Việt Nam '
    'hoặc đối chiếu điều khoản văn bản, bạn cứ đặt câu hỏi tại đây nhé.'
)

_RECIPE_ASTRONOMY_RESPONSE = (
    'VietLex hỗ trợ tra cứu và nghiên cứu pháp luật. '
    'Yêu cầu nấu ăn hoặc giải thích thiên văn này nằm ngoài phạm vi; '
    'bạn có thể gửi một câu hỏi pháp luật cụ thể.'
)

_SMALLTALK_RESPONSE = (
    'VietLex hỗ trợ tra cứu và nghiên cứu pháp luật Việt Nam. '
    'Yêu cầu này nằm ngoài phạm vi pháp lý; '
    'bạn có thể gửi một câu hỏi hoặc tình huống pháp luật cụ thể để tôi tra cứu.'
)


def deterministic_guidance(query: str) -> tuple[str, str] | None:
    """Return short deterministic guidance for greetings, chitchat, or underspecified money claims."""
    folded = fold_topic_text(query)
    topics = extract_official_topic_phrases(query, limit=8)
    transaction = _TRANSACTION_PATTERN.search(folded)
    if 'giu tien' in folded and not topics and not transaction:
        return (
            'clarification',
            'Tôi chưa đủ dữ kiện và không thể khẳng định chắc thắng. '
            'Khoản tiền phát sinh từ giao dịch hoặc thỏa thuận nào? '
            'Bạn có chứng từ chuyển tiền, tin nhắn hoặc giấy tờ gì? '
            'Thời điểm giao tiền, hạn trả và yêu cầu hoàn trả là khi nào?',
        )

    legal_signal = bool(topics) or bool(_LEGAL_SIGNAL_PATTERN.search(folded))
    if legal_signal:
        return None

    # Positive greeting/meta/nonlegal requests only; never reject an unknown legal term
    # merely because it is missing from the curated topic dictionary.
    clauses = [
        part.strip(' .,!?:')
        for part in re.split(r'\s+va\s+|[,;?!]+', folded)
        if part.strip(' .,!?:')
    ]
    clauses = [re.sub(r'^vl-audit-\d{8}:\s*', '', part) for part in clauses]
    clauses = [part for part in clauses if part]
    if not clauses:
        return None

    all_nonlegal = all(
        _GREETING_PATTERN.fullmatch(part)
        or _THANKS_OR_FAREWELL_PATTERN.fullmatch(part)
        or _META_ASSISTANT_PATTERN.fullmatch(part)
        or _RECIPE_OR_ASTRONOMY_PATTERN.fullmatch(part)
        or _CHITCHAT_SMALLTALK_PATTERN.fullmatch(part)
        for part in clauses
    )
    if not all_nonlegal:
        return None

    if all(_RECIPE_OR_ASTRONOMY_PATTERN.fullmatch(part) for part in clauses):
        return ('unsupported_intent', _RECIPE_ASTRONOMY_RESPONSE)
    if all(_THANKS_OR_FAREWELL_PATTERN.fullmatch(part) for part in clauses):
        return ('unsupported_intent', _THANKS_RESPONSE)
    if any(_CHITCHAT_SMALLTALK_PATTERN.fullmatch(part) or _RECIPE_OR_ASTRONOMY_PATTERN.fullmatch(part) for part in clauses):
        return ('unsupported_intent', _SMALLTALK_RESPONSE)
    return ('unsupported_intent', _GREETING_RESPONSE)
