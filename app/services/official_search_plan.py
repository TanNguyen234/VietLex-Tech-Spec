"""Deterministic, private query planning and request-scoped reading budgets."""
from dataclasses import dataclass
import re

from app.services.legal_topic_terms import extract_official_topic_phrases, fold_topic_text, local_rescue_terms

DOCUMENT_REFERENCE = re.compile(r"(?<![\w/-])\d{1,4}/(?:\d{4}/[A-ZĐÐ][A-ZĐÐ0-9-]{1,29}|VBHN-[A-ZĐÐ0-9-]{1,29})(?![\w/-])", re.I)

@dataclass(frozen=True)
class ReadingProfile:
    version: str = "official-deep-v1"
    total_seconds: float = 60
    discovery_seconds: float = 15
    read_seconds: float = 40
    context_tokens: int = 8000
    evidence_limit: int = 16
    source_limit: int = 8
    query_limit: int = 5


DEEP_READING = ReadingProfile()


class ProfiledContexts(list):
    """Carry the budget to the final prompt without changing HTTP or global state."""
    def __init__(self, contexts, profile: ReadingProfile):
        super().__init__(contexts)
        self.context_profile = profile


@dataclass(frozen=True)
class OfficialSearchPlan:
    original_question: str  # Local only; never serialize this into search diagnostics.
    queries: tuple[str, ...]
    topics: tuple[str, ...]
    status: str
    current_required: bool
    actors: tuple[str, ...]
    actions: tuple[str, ...]
    intents: tuple[str, ...]
    as_of: str | None
    jurisdictions: tuple[str, ...] = ()
    reference: str | None = None

    @property
    def objects(self):
        return self.topics


def sanitized_subject(question: str) -> str:
    """Drop explicit identity/contact/address spans before selecting fallback words."""
    clean = str(question or "")[:2000]
    clean = re.sub(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b|https?://\S+", " ", clean)
    clean = re.sub(r"(?i)(?:tôi tên|tên tôi(?: là)?|tôi là|họ tên(?: là)?)\s+[^,;.!?\n]+", " ", clean)
    clean = re.sub(r"(?i)(?:địa chỉ|ở số|sống tại|cư trú tại|số điện thoại|số căn cước|cccd|cmnd)\s*:?[^;.!?\n]+", " ", clean)
    clean = re.sub(r"\b\d[\d\s./%-]*\b", " ", clean)
    # Unknown proper names must not leave the process, even without a marker.
    words = re.findall(r"[^\W\d_]+", clean, re.UNICODE)
    safe = [word for index, word in enumerate(words)
            if not (word[:1].isupper() and word[1:].islower())
            or (index == 0 and len(words) > 1 and words[1].islower()
                and fold_topic_text(word) not in {"nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo", "dang", "bui", "do", "ho"})]
    terms = set(local_rescue_terms(" ".join(safe), limit=40))
    signal = [i for i, word in enumerate(safe) if fold_topic_text(word) in terms]
    if len(signal) < 2:
        return ""
    # Preserve connective words inside the situation (e.g. "lối đi chung").
    return " ".join(word.casefold() for word in safe[signal[0]:signal[-1] + 1][:16])


def build_official_search_plan(question: str) -> OfficialSearchPlan:
    original = str(question or "")[:2000]
    from app.services.chat_official_supplement import _current_applicability_intent, _temporal_query_terms
    topics = extract_official_topic_phrases(original, limit=8)
    recognized = bool(topics)
    folded = fold_topic_text(original)
    if "nhap khau phe lieu" in folded:
        topics = ("nhập khẩu phế liệu", *(t for t in topics if t not in {"nhập khẩu", "phế liệu", "nhập phế liệu"}))
    aliases = []
    if "loi di" in folded:
        aliases.append("quyền về lối đi qua")
        topics = tuple(dict.fromkeys((*topics, "lối đi")))
    if re.search(r"(?:sep|cong ty).{0,60}(?:duoi|bat nghi|cho nghi)", folded):
        aliases.append("chấm dứt hợp đồng lao động")
    jurisdictions = []
    for match in re.finditer(r"\b(tỉnh|thành phố)\s+([^;,.!?\n]+)", original, re.I):
        region = []
        for word in match.group(2).split()[:4]:
            if word[:1].isupper():
                region.append(word)
            else:
                break
        if region:
            jurisdictions.append(match.group(1).lower() + " " + " ".join(region))
    subject = " ".join(topics) if topics else sanitized_subject(original)
    subject = " ".join(subject.split()[:16])
    current = _current_applicability_intent(original)
    reference = DOCUMENT_REFERENCE.search(original)
    date = re.search(r"(?:tại ngày|tính đến|as of)\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})", original, re.I)
    current = current or bool(date)
    temporal = " ".join(_temporal_query_terms(original))
    family = None
    topic_text = fold_topic_text(" ".join((*topics, subject, *aliases)))
    for cues, title in (
        (("thu viec", "luong", "cham dut hop dong lao dong"), "Bộ luật Lao động"),
        (("phe lieu", "moi truong"), "Luật Bảo vệ môi trường"),
        (("dat dai", "quyen su dung dat"), "Luật Đất đai"),
        (("thue nha", "dat coc", "loi di"), "Bộ luật Dân sự"),
    ):
        if any(cue in topic_text for cue in cues):
            family = title
            break
    queries = []
    if reference or len(subject.split()) >= 2:
        for value in ((reference.group().upper() + " " + subject) if reference else " ".join((subject, temporal)),
                      family or (aliases[0] if aliases else f"{subject} điều kiện thủ tục"),
                      aliases[0] if aliases else topics[0] if topics else subject,
                      f"{subject} {jurisdictions[0]}" if jurisdictions else topics[-1] if len(topics) > 1 else f"{subject} hướng dẫn",
                      f"{family or subject} sửa đổi hiệu lực"):
            value = " ".join(value.split())[:220]
            if value and value not in queries:
                queries.append(value)
    actors = tuple(x for x in ("người lao động", "doanh nghiệp", "cơ sở", "chủ nhà") if fold_topic_text(x) in folded)
    actions = tuple(x for x in ("nhập khẩu", "thuê", "đặt cọc", "chấm dứt", "chuyển nhượng", "khởi kiện") if fold_topic_text(x) in folded)
    intents = tuple(x for x in ("điều kiện", "thủ tục", "giấy phép", "thời hạn", "xử phạt", "hiệu lực") if fold_topic_text(x) in folded)
    reference_only = reference is not None and not topics and set(local_rescue_terms(subject, limit=40)) <= {"tra", "cuu", "van", "ban", "luat"}
    if reference_only:
        queries = [reference.group().upper()]
    return OfficialSearchPlan(original, tuple(queries[:5]), tuple(topics) or ((subject,) if queries else ()),
                              "reference" if reference_only else "recognized" if recognized else "expanded" if queries else "unknown",
                              current, actors, actions, intents, date.group(1) if date else None, tuple(jurisdictions),
                              reference.group().upper() if reference else None)
