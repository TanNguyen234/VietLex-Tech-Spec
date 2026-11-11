"""Deterministic topic extraction for private local rescue and web queries."""

from __future__ import annotations

import re
import unicodedata


LEGAL_TOPIC_PHRASES = (
    "thuê nhà",
    "đặt cọc",
    "thử việc",
    "tiền lương",
    "mức lương",
    "lương",
    "nhập phế liệu",
    "phế liệu",
    "nhập khẩu",
    "xuất khẩu",
    "giấy phép môi trường",
    "cụm công nghiệp",
    "bảo hiểm xã hội",
    "bảo hiểm thất nghiệp",
    "nghỉ thai sản",
    "nghỉ phép năm",
    "hợp đồng lao động",
    "chấm dứt hợp đồng",
    "trợ cấp thôi việc",
    "trợ cấp thất nghiệp",
    "tai nạn lao động",
    "thuế thu nhập cá nhân",
    "thuế giá trị gia tăng",
    "thuế thu nhập doanh nghiệp",
    "hóa đơn điện tử",
    "đăng ký kinh doanh",
    "giấy phép kinh doanh",
    "điều kiện kinh doanh",
    "quyền sử dụng đất",
    "chuyển nhượng đất",
    "tranh chấp đất",
    "bồi thường thiệt hại",
    "sở hữu trí tuệ",
    "dữ liệu cá nhân",
    "bảo vệ dữ liệu",
    "xử phạt vi phạm",
    "thời hiệu xử phạt",
    "khởi kiện",
    "tranh chấp",
    "thừa kế",
    "di chúc",
    "ly hôn",
    "kết hôn",
    "quốc tịch",
    "tạm giam",
    "tạm giữ",
    "lãi suất",
)

# Only curated phrases leave the process; personal narrative never does.
_TOPIC_ALIASES = {
    "thuê trọ": "thuê nhà", "nhà trọ": "thuê nhà", "phòng trọ": "thuê nhà",
    "thuê phòng": "thuê nhà", "tiền cọc": "đặt cọc", "cọc thuê": "đặt cọc",
    "nghỉ hằng năm": "nghỉ phép năm", "nghỉ hàng năm": "nghỉ phép năm",
    "nghỉ thường niên": "nghỉ phép năm",
}

_LOCAL_STOPWORDS = frozenset(
    "a ai anh bao ban bang bi bo cac cai cho chinh chi chu co cong cung cua da dang day de den dieu do dong duoc em gi giua hai hay hon ho khi khong la lai lam len lieu ma moi mot muc nay neu ngay nhan nhieu nhu noi nua o phai phan qua ra rang rat roi sau se so su tai theo thi thang the thoi toi tram trong trieu tu tuong ty viec voi vua va van vi xuong y".split()
)


def fold_topic_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(value or "").casefold())
    unmarked = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", unmarked.replace("đ", "d")).strip()


def contains_topic_phrase(text: str, topic: str) -> bool:
    """Match a complete canonical phrase, including its curated aliases."""
    folded = fold_topic_text(text)
    canonical = fold_topic_text(topic)
    if not canonical:
        return False
    phrases = (canonical, *(
        fold_topic_text(alias)
        for alias, target in _TOPIC_ALIASES.items()
        if fold_topic_text(target) == canonical
    ))
    if any(
        re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", folded)
        for phrase in phrases
    ):
        return True

    # Curated legal paraphrase; avoid rescanning every known topic for each
    # clause of a long law when the requested phrase is absent.
    return canonical == "nhap phe lieu" and bool(
        re.search(r"(?<![a-z0-9])nhap khau phe lieu(?![a-z0-9])", folded)
    )


def extract_official_topic_phrases(query: str, *, limit: int = 4) -> tuple[str, ...]:
    """Return only recognized legal terms; never forward arbitrary query text."""
    folded = fold_topic_text(query)
    canonical_matches: list[tuple[int, int, str]] = []
    alias_matches: list[tuple[int, int, str]] = []
    for phrase in LEGAL_TOPIC_PHRASES:
        normalized = fold_topic_text(phrase)
        match = re.search(
            rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
            folded,
        )
        if match:
            canonical_matches.append((match.start(), match.end(), phrase))
    for phrase, topic in _TOPIC_ALIASES.items():
        normalized = fold_topic_text(phrase)
        match = re.search(
            rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
            folded,
        )
        if match:
            alias_matches.append((match.start(), match.end(), topic))

    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(
        canonical_matches,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if any(
            candidate[0] < item[1] and item[0] < candidate[1]
            for item in selected
        ):
            continue
        selected.append(candidate)
    for candidate in sorted(
        alias_matches,
        key=lambda item: (item[0], -(item[1] - item[0])),
    ):
        if candidate[2] not in {item[2] for item in selected}:
            # A curated alias can overlap a different canonical topic in a
            # compound phrase, as in "cọc thuê nhà" (deposit + rental).
            selected.append(candidate)
    topics = tuple(
        dict.fromkeys(item[2] for item in sorted(selected, key=lambda item: item[0]))
    )
    return topics[: max(0, limit)]


def matches_legal_situation(query: str, text: str) -> bool:
    """Bounded rental/deposit gate, not a legal-validity classifier."""
    topics = extract_official_topic_phrases(query)
    if "thuê nhà" not in topics:
        return True
    folded = fold_topic_text(text)
    if (
        re.search(r"truoc.{0,60}1991", folded)
        and "1991" not in fold_topic_text(query)
    ):
        return False
    rental = "thuê nhà" in extract_official_topic_phrases(text, limit=32)
    deposit = "đặt cọc" in extract_official_topic_phrases(text, limit=32)
    if "đặt cọc" in topics:
        if "lao dong" in folded and "nuoc ngoai" in folded and not rental:
            return False
        # General civil deposit provisions may help even without rental wording.
        return deposit and (rental or "bao dam" in folded or "hop dong" in folded)
    return rental


def local_rescue_terms(query: str, *, limit: int = 8) -> tuple[str, ...]:
    """Return bounded lexical terms for in-process, hash-verified clause rescue."""
    folded = fold_topic_text(query)
    terms = re.findall(r"[a-z]+", folded)
    selected: list[str] = []
    for term in terms:
        if len(term) < 3 or term in _LOCAL_STOPWORDS or term.isdecimal():
            continue
        if term not in selected:
            selected.append(term)
        if len(selected) >= max(0, limit):
            break
    return tuple(selected)
