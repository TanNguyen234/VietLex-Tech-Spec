"""Expected current legal instruments and superseded versions, checked against retrieved evidence.

Retrieval can return only the instruments that are present in the local corpus. When a
question concerns a current instrument that the corpus lacks (or holds only in a superseded
version), the chat pipeline must not answer from the old text as if it were current. It
instead asks the official-source supplement for the current instrument, using the explicit
search queries registered here, and keeps the corpus evidence only as labelled context.

Only headers are matched (the first four lines of a context: citation, source, title, number),
so a body paragraph that merely mentions another law does not count as that law being present.
Diagnostics never carry the question text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.legal_topic_terms import fold_topic_text


@dataclass(frozen=True)
class ExpectedInstrument:
    key: str
    cues: tuple[str, ...]           # folded phrases; the question must contain one
    markers: tuple[str, ...]        # folded phrases; a header must contain one to count as present
    queries: tuple[str, ...]        # explicit official-source search queries
    topic_phrases: tuple[str, ...]  # folded phrases used to keep fetched text on topic
    reader_hint: str = ""           # extra question text that steers the deep reader's page choice


@dataclass(frozen=True)
class SupersededInstrument:
    key: str
    markers: tuple[str, ...]  # folded phrases identifying the old text in a header
    year: str                 # the question may keep this text only if it names this year
    replaced_by: str
    before_year: str = ""     # family rule: only texts whose number year is earlier than this are superseded


EXPECTED_INSTRUMENTS: tuple[ExpectedInstrument, ...] = (
    ExpectedInstrument(
        key="social_insurance_2024",
        cues=("bao hiem xa hoi", "luong huu", "bhxh"),
        markers=("41/2024/qh15", "luat bao hiem xa hoi 2024"),
        queries=(
            "Luật Bảo hiểm xã hội 2024 hưởng lương hưu điều kiện thời gian đóng",
            "Luật Bảo hiểm xã hội 41/2024/QH15",
        ),
        topic_phrases=("bao hiem xa hoi", "luong huu"),
    ),
    ExpectedInstrument(
        key="land_law_2024",
        cues=("dat dai", "quyen su dung dat", "so do", "giay tay", "chuyen nhuong dat"),
        markers=("31/2024/qh15", "luat dat dai 2024", "hop nhat luat dat dai"),
        queries=(
            "Văn bản hợp nhất Luật Đất đai",
            "Luật Đất đai 2024 chuyển nhượng quyền sử dụng đất",
        ),
        topic_phrases=("dat dai", "quyen su dung dat", "viec cong chung"),
        reader_hint="việc công chứng, chứng thực hợp đồng chuyển nhượng quyền sử dụng đất",
    ),
    ExpectedInstrument(
        key="notary_law_2024",
        cues=("cong chung", "chung thuc hop dong"),
        markers=("46/2024/qh15", "luat cong chung 2024"),
        queries=(
            "Luật Công chứng 2024 công chứng hợp đồng chuyển nhượng bất động sản",
            "Luật Công chứng 46/2024/QH15",
        ),
        topic_phrases=("cong chung", "bat dong san", "giao dich phai cong chung", "cong chung giao dich ve bat dong san"),
        reader_hint="giao dịch phải công chứng; thẩm quyền công chứng giao dịch bất động sản",
    ),
    ExpectedInstrument(
        key="traffic_penalty_decree_2024",
        cues=("nong do con", "say ruou", "bia ruou", "vuot den", "den tin hieu", "giu xe", "tam giu", "phat nguoi"),
        markers=("168/2024/nd-cp", "nghi dinh 168/2024"),
        queries=(
            "Nghị định 168/2024/NĐ-CP xử phạt vi phạm hành chính giao thông đường bộ",
            "Nghị định 168/2024/NĐ-CP nồng độ cồn tước giấy phép lái xe tạm giữ phương tiện",
        ),
        topic_phrases=("xu phat", "giao thong", "nong do con", "tam giu", "tuoc quyen su dung giay phep lai xe"),
    ),
    ExpectedInstrument(
        key="personal_income_tax_2025",
        cues=("thu nhap ca nhan", "tncn", "giam tru gia canh", "thu nhap tinh thue"),
        markers=("109/2025/qh15", "luat thue thu nhap ca nhan 2025"),
        queries=(
            "Luật Thuế thu nhập cá nhân 2025 giảm trừ gia cảnh biểu thuế",
            "Luật Thuế thu nhập cá nhân 109/2025/QH15",
        ),
        topic_phrases=("thu nhap ca nhan", "giam tru gia canh"),
    ),
    ExpectedInstrument(
        key="tax_administration_2025",
        cues=("cham nop", "quan ly thue", "nop thue cham"),
        markers=("108/2025/qh15",),
        queries=(
            "Luật Quản lý thuế 2025 tiền chậm nộp mức tính",
            "Luật Quản lý thuế 108/2025/QH15 chậm nộp",
        ),
        topic_phrases=("cham nop", "quan ly thue"),
    ),
    ExpectedInstrument(
        key="minimum_wage_region",
        cues=("luong toi thieu", "muc luong toi thieu"),
        markers=("luong toi thieu vung", "293/2025/nd-cp"),
        queries=(
            "Nghị định 293/2025/NĐ-CP mức lương tối thiểu vùng",
            "mức lương tối thiểu vùng nghị định hiện hành",
        ),
        topic_phrases=("luong toi thieu",),
    ),
    ExpectedInstrument(
        key="pet_protection_law_2026",
        cues=("thu cung", "cho canh"),
        markers=("bao ve thu cung",),
        queries=("Luật Bảo vệ thú cưng 2026",),
        topic_phrases=("thu cung",),
    ),
)

SUPERSEDED_INSTRUMENTS: tuple[SupersededInstrument, ...] = (
    SupersededInstrument("bhxh_law_2014", ("58/2014/qh13", "luat bao hiem xa hoi 2014"), "2014", "Luật Bảo hiểm xã hội 2024"),
    SupersededInstrument("land_law_2013", ("45/2013/qh13", "luat dat dai 2013"), "2013", "Luật Đất đai 2024"),
    SupersededInstrument("land_law_2003", ("13/2003/qh11", "luat dat dai 2003"), "2003", "Luật Đất đai 2024"),
    SupersededInstrument("notary_law_2006", ("82/2006/qh11", "luat cong chung 2006"), "2006", "Luật Công chứng 2014"),
    SupersededInstrument("traffic_decree_1977", ("143-cp", "dieu le ve phat vi canh"), "1977", "Nghị định 168/2024/NĐ-CP"),
    SupersededInstrument("traffic_decree_2019", ("100/2019/nd-cp",), "2019", "Nghị định 168/2024/NĐ-CP"),
    SupersededInstrument("pit_law_2007", ("04/2007/qh12", "luat thue thu nhap ca nhan 2007"), "2007", "Luật Thuế thu nhập cá nhân 2025"),
    SupersededInstrument("pit_law_2012", ("26/2012/qh13",), "2012", "Luật Thuế thu nhập cá nhân 2025"),
    SupersededInstrument("tax_admin_2006", ("78/2006/qh11", "luat quan ly thue 2006"), "2006", "Luật Quản lý thuế 2019"),
    SupersededInstrument("tax_admin_2012", ("21/2012/qh13",), "2012", "Luật Quản lý thuế 2019"),
    SupersededInstrument("min_wage_decree_2022", ("38/2022/nd-cp", "nghi dinh 38/2022"), "2022", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("bhxh_decree_2006", ("152/2006/nd-cp", "nghi dinh 152/2006"), "2006", "Luật Bảo hiểm xã hội 2014 và 2024"),
    SupersededInstrument("marriage_law_2000", ("22/2000/qh10", "luat hon nhan va gia dinh 2000"), "2000", "Luật Hôn nhân và gia đình 2014"),
    SupersededInstrument("marriage_guidance_2000", ("02/2000/nq-hdtp",), "2000", "Luật Hôn nhân và gia đình 2014"),
    SupersededInstrument("leave_instruction_1959", ("028-ttg",), "1959", "Bộ luật Lao động 2019"),
    SupersededInstrument("nad_law_1987_1992", ("lct/hdnn8",), "1992", "văn bản hiện hành cùng lĩnh vực"),
    SupersededInstrument("court_instruction_1990", ("01-tandtc/ct",), "1990", "văn bản hiện hành của Tòa án nhân dân tối cao"),
    SupersededInstrument("animal_health_ordinance_1993", ("phap lenh thu y",), "1993", "Luật Thú y 2015"),
    # Outdated texts that the official-web supplement returned as current.
    SupersededInstrument("notary_law_2014", ("53/2014/qh13", "luat cong chung 2014"), "2014", "Luật Công chứng 2024 (46/2024/QH15), hiệu lực 01/07/2025"),
    SupersededInstrument("real_estate_business_law_2014", ("66/2014/qh13", "luat kinh doanh bat dong san 2014"), "2014", "Luật Kinh doanh bất động sản 2023 (29/2023/QH15), hiệu lực 01/01/2025 (Điều 82 K2); hợp đồng xác lập trước đó xem Điều 83"),
    SupersededInstrument("tax_admin_2019", ("38/2019/qh14",), "2019", "Luật Quản lý thuế 2025 (108/2025/QH15), hiệu lực 01/01/2026"),
    SupersededInstrument("min_wage_decree_2012", ("103/2012/nd-cp",), "2012", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2013", ("182/2013/nd-cp",), "2013", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2014", ("103/2014/nd-cp",), "2014", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2015", ("122/2015/nd-cp",), "2015", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2016", ("153/2016/nd-cp",), "2016", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2019", ("90/2019/nd-cp",), "2019", "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)"),
    SupersededInstrument("min_wage_decree_2024", ("74/2024/nd-cp",), "2024", "Nghị định 293/2025/NĐ-CP (hiệu lực 01/01/2026)"),
    SupersededInstrument("min_wage_circular_2012", ("29/2012/tt-bldtbxh",), "2012", "thông tư hướng dẫn Nghị định 103/2012 (đã thay thế)"),
    SupersededInstrument("min_wage_circular_2013", ("33/2013/tt-bldtbxh",), "2013", "thông tư hướng dẫn Nghị định 182/2013 (đã thay thế)"),
    SupersededInstrument("labour_circular_1962", ("309-ldtl",), "1962", "Bộ luật Lao động 2019, Điều 113"),
    SupersededInstrument("rabies_decree_2007", ("05/2007/nd-cp",), "2007", "Nghị định 05/2020/NĐ-CP (bãi bỏ, Điều 1 mục 26)"),
    SupersededInstrument("min_wage_family_before_2025", ("luong toi thieu vung",), "2025",
                         "Nghị định 293/2025/NĐ-CP (mức lương tối thiểu vùng hiện hành)", before_year="2025"),
    SupersededInstrument("min_wage_general_2005", ("118/2005/nd-cp",), "2005", "văn bản lương tối thiểu chung đã thay thế"),
    SupersededInstrument("min_wage_general_2011", ("22/2011/nd-cp",), "2011", "văn bản lương tối thiểu chung đã thay thế (sau 2013)"),
    SupersededInstrument("min_wage_decree_2011", ("70/2011/nd-cp",), "2011", "các nghị định mức lương tối thiểu vùng sau 2011"),
    SupersededInstrument("min_wage_circular_2011", ("23/2011/tt-bldtbxh",), "2011", "thông tư hướng dẫn Nghị định 70/2011 (đã thay thế)"),
)

# Off-topic official texts: international judicial-assistance notices and similar instruments.
# They are dropped unless the question itself concerns cross-border matters.
_INTERNATIONAL_CUE = re.compile(
    r"(?<![a-z])(?:nuoc ngoai|quoc te|tuong tro|uy thac|lanh su|belarut|ban nuoc|nguoi nuoc ngoai|phap nhan nuoc ngoai)(?![a-z])"
)
_OFF_TOPIC_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("international_judicial_assistance", ("tb-lpqt", "tuong tro tu phap", "hiep dinh tuong tro")),
)

_YEAR = re.compile(r"(?:19|20)\d{2}")


@dataclass(frozen=True)
class InstrumentAssessment:
    kept_contexts: tuple
    missing: tuple[ExpectedInstrument, ...]
    queries: tuple[str, ...]
    topic_phrases: tuple[str, ...]
    diagnostics: dict
    reader_hint: str = ""


_METADATA_PREFIXES = (
    "[", "nguon", "tieu de", "dan chieu", "id tai lieu", "so hieu", "hieu luc",
    "co quan ban hanh", "sha-256", "thoi diem doc", "phuong thuc doc",
    "tep pdf", "pham vi trang pdf", "doc mot phan pdf",
)


def _header(context: object) -> str:
    """Return the metadata block only; the first body line ends it."""
    lines: list[str] = []
    for raw in str(context).replace("\r", "\n").splitlines()[:12]:
        line = fold_topic_text(raw)
        if not line:
            continue
        if not line.startswith(_METADATA_PREFIXES):
            break
        lines.append(line)
    return " ".join(lines)


def _cue_present(folded_question: str, cue: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", folded_question) is not None


_NUMBER_YEAR = re.compile(r"\d{1,4}/((?:19|20)\d{2})/")


def _number_year(header: str) -> int | None:
    match = _NUMBER_YEAR.search(header)
    return int(match.group(1)) if match else None


def drop_superseded_contexts(question: str, contexts) -> tuple[list, dict[str, int]]:
    """Remove texts whose header names a superseded instrument the question does not ask about,
    and off-topic official texts unless the question concerns cross-border matters."""
    question_text = str(question or "")
    question_years = set(_YEAR.findall(question_text))
    cross_border = _INTERNATIONAL_CUE.search(fold_topic_text(question_text)) is not None
    kept: list = []
    dropped: dict[str, int] = {}
    for context in contexts:
        header = _header(context)
        number_year = _number_year(header)
        superseded = next(
            (
                item
                for item in SUPERSEDED_INSTRUMENTS
                if any(marker in header for marker in item.markers)
                and (
                    # Family rule: the text's own number year decides, and naming that year keeps it.
                    (number_year is not None and number_year < int(item.before_year)
                     and str(number_year) not in question_years)
                    if item.before_year
                    else item.year not in question_years
                )
            ),
            None,
        )
        key = superseded.key if superseded is not None else None
        if key is None and not cross_border:
            key = next(
                (
                    f"off_topic:{name}"
                    for name, markers in _OFF_TOPIC_MARKERS
                    if any(marker in header for marker in markers)
                ),
                None,
            )
        if key is not None:
            dropped[key] = dropped.get(key, 0) + 1
            continue
        kept.append(context)
    return kept, dropped


def assess_expected_instruments(question: str, contexts) -> InstrumentAssessment:
    """Drop superseded texts, then report expected current instruments the evidence lacks."""
    folded_question = fold_topic_text(question)
    kept, dropped = drop_superseded_contexts(question, contexts)
    applicable = [
        entry
        for entry in EXPECTED_INSTRUMENTS
        if any(_cue_present(folded_question, cue) for cue in entry.cues)
    ]
    headers = [_header(context) for context in kept]
    missing = tuple(
        entry
        for entry in applicable
        if not any(marker in header for marker in entry.markers for header in headers)
    )
    queries: list[str] = []
    topics: list[str] = []
    for entry in missing:
        queries.extend(entry.queries[:2])
        topics.extend(entry.topic_phrases)
    diagnostics = {
        "matched_entries": [entry.key for entry in applicable],
        "missing_entries": [entry.key for entry in missing],
        "superseded_dropped": dropped,
        "query_count": len(dict.fromkeys(queries)),
    }
    return InstrumentAssessment(
        kept_contexts=tuple(kept),
        missing=missing,
        queries=tuple(dict.fromkeys(queries))[:4],
        topic_phrases=tuple(dict.fromkeys(topics)),
        diagnostics=diagnostics,
        reader_hint=" ".join(dict.fromkeys(entry.reader_hint for entry in missing if entry.reader_hint)),
    )
