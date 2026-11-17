"""Bounded metadata lookup for curated primary-law titles in the selected corpus."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from threading import Lock
from typing import Any

from app.ingestion.legal_text import EvidenceChunk, chunk_document
from app.services.source_quality import assess_source_quality
from app.services.legal_topic_terms import (
    contains_topic_phrase,
    extract_official_topic_phrases,
    fold_topic_text,
    local_rescue_terms,
    matches_legal_situation,
    normalize_colloquial_query,
)


_MAX_TITLE_CANDIDATES = 10
_MAX_DOCUMENT_LOADS = 2
_MAX_EVIDENCE = 3
_MAX_CONTEXT_TOKENS = 720
_PRIMARY_RESCUE_TIMEOUT_SECONDS = 8.0
_DOCUMENT_ID = re.compile(r"\b\d+\s*/\s*(?:19|20)\d{2}\s*/\s*[a-z]{1,8}\d*\b")
_ARTICLE_REFERENCE = re.compile(r"\bdieu\s+(\d+)(?:\s*[-–]\s*(\d+))?")
_TOKEN = re.compile(r"[a-z0-9]+")
_PREPARED_DOCUMENT_LOCK = Lock()
_PREPARED_DOCUMENT_CACHE: OrderedDict[
    tuple[Any, ...],
    tuple[dict[tuple[Any, ...], int], tuple[tuple[EvidenceChunk, str, frozenset[str]], ...]],
] = OrderedDict()
_PREPARED_DOCUMENT_CACHE_MAX = 32


def _prepared_chunks_for_document(
    *,
    document_id: int,
    actual_digest: str,
    metadata: Any,
    content: str,
    preserve_unit_max_tokens: int,
    preserve_article_max_tokens: int | None,
    require_preamble: bool,
    chunk_max: int,
    overlap: int,
) -> tuple[dict[tuple[Any, ...], int], tuple[tuple[EvidenceChunk, str, frozenset[str]], ...]]:
    key = (
        document_id,
        actual_digest,
        preserve_unit_max_tokens,
        preserve_article_max_tokens,
        require_preamble,
        chunk_max,
        overlap,
    )
    with _PREPARED_DOCUMENT_LOCK:
        cached = _PREPARED_DOCUMENT_CACHE.get(key)
        if cached is not None:
            _PREPARED_DOCUMENT_CACHE.move_to_end(key)
            return cached

    raw_chunks = chunk_document(
        metadata,
        content,
        preserve_unit_max_tokens=preserve_unit_max_tokens,
        preserve_article_max_tokens=preserve_article_max_tokens,
        require_preamble=require_preamble,
        max_tokens=chunk_max,
        overlap_tokens=overlap,
    )
    group_counts = dict(Counter((chunk.article, chunk.clause) for chunk in raw_chunks))
    prepared = tuple(
        (chunk, folded := fold_topic_text(chunk.text), frozenset(_TOKEN.findall(folded)))
        for chunk in raw_chunks
    )
    entry = (group_counts, prepared)
    with _PREPARED_DOCUMENT_LOCK:
        _PREPARED_DOCUMENT_CACHE[key] = entry
        _PREPARED_DOCUMENT_CACHE.move_to_end(key)
        while len(_PREPARED_DOCUMENT_CACHE) > _PREPARED_DOCUMENT_CACHE_MAX:
            _PREPARED_DOCUMENT_CACHE.popitem(last=False)
    return entry


def _heading_phrase_overlap(query: str, text: str) -> int:
    """Favor a clause heading that names the action in the question."""
    folded_query = re.sub(
        r"\bhet(?=\s+thoi gian thu viec\b)",
        "ket thuc",
        fold_topic_text(query),
    )
    query_tokens = _TOKEN.findall(folded_query)
    heading_tokens = _TOKEN.findall(fold_topic_text(text))[:18]
    heading = " " + " ".join(heading_tokens) + " "
    for size in range(min(6, len(query_tokens)), 1, -1):
        if any(
            " " + " ".join(query_tokens[start : start + size]) + " " in heading
            for start in range(len(query_tokens) - size + 1)
        ):
            return size
    return 0


def _is_keyword_only_clause(text: str) -> bool:
    """Identify a bare list entry without a usable condition or rule."""
    payload = re.split(r"\b\d+\.\s*", text)[-1]
    return len(payload.split()) <= 3


def _trial_facets(query: str) -> tuple[str, ...]:
    """Allocate the bounded evidence slots to issues actually asked about."""
    if not contains_topic_phrase(query, "thử việc"):
        return ()
    folded = fold_topic_text(query)
    facets = []
    if re.search(r"\b(?:thoi gian|thoi han|bao lau|ngay|thang)\b", folded):
        facets.append("trial_duration")
    if re.search(r"\bluong\b", folded):
        facets.append("trial_wage")
    if re.search(r"\b(?:nghi|huy|cham dut|bao truoc)\b", folded):
        facets.append("trial_termination")
    return tuple(facets)


@dataclass(frozen=True)
class _LawTitle:
    title_base: str
    year: str
    topics: tuple[str, ...]
    document_number: str
    legal_types: tuple[str, ...] = ("luat", "bo luat")
    exact_title_only: bool = True
    title_exclude: tuple[str, ...] = ()
    domain_terms: tuple[str, ...] = ()
    # Query-gated statutory concept rules: (folded_query_regex, (chunk_phrases_that_must_match...))
    domain_rules: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def exact_title(self) -> str:
        return f"{self.title_base} {self.year}"


@dataclass(frozen=True)
class PrimaryLawRescueResult:
    evidence: tuple[EvidenceChunk, ...]
    diagnostics: dict[str, Any]


_LABOR = _LawTitle(
    "Bộ luật Lao động",
    "2019",
    ("thử việc", "tiền lương", "mức lương", "lương", "chấm dứt hợp đồng", "hợp đồng lao động", "nghỉ phép năm",
     "thực tập", "sa thải", "nghỉ phép", "lương tối thiểu", "trợ cấp thôi việc"),
    "45/2019/QH14",
    domain_rules=(
        (r"thuc tap|khong ky hop dong|part[- ]?time", ("khai niem hop dong lao dong", "giao ket hop dong lao dong", "hinh thuc hop dong", "bang loi noi", "bang van ban")),
        (r"don phuong cham dut|nghi viec|duoi viec|bao truoc|xin nghi|muon nghi|nghi phai|khong xac dinh thoi han", ("don phuong cham dut", "bao truoc", "nghia vu cua nguoi lao dong khi don phuong", "it nhat 45 ngay", "khong xac dinh thoi han")),
        (r"giu luong|no luong|tra luong|doi tien|so bao hiem", ("thanh toan day du", "nguyen tac tra luong", "tra lai ban chinh", "bao hiem xa hoi", "thoi han thanh toan")),
        (r"kien|giai quyet tranh chap|hoa giai|toa an|thanh tra", ("hoa giai vien lao dong", "toa an nhan dan", "thoi hieu yeu cau giai quyet tranh chap lao dong ca nhan", "tham quyen giai quyet tranh chap lao dong")),
        (r"thoi hieu|bao lau|nop don", ("thoi hieu yeu cau giai quyet tranh chap lao dong ca nhan", "06 thang", "09 thang", "01 nam")),
        (r"nghi phep|nghi hang nam|ngay nghi|ngay phep|phep nam", ("nghi hang nam", "lam viec du 12 thang", "huong nguyen luong")),
        (r"thuc tap|khong ky hop dong|khong co hop dong|luong toi thieu|3 trieu|quyen loi", ("muc luong toi thieu", "tien luong toi thieu")),
        (r"sa thai|tro cap thoi viec|tro cap mat viec|bi cho nghi|bi duoi viec|boi thuong|nam lam viec|5 nam|tham nien", ("don phuong cham dut hop dong lao dong trai phap luat", "tro cap thoi viec", "nghia vu cua nguoi su dung lao dong khi don phuong cham dut", "mot nua thang tien luong")),
    ),
)
_CIVIL = _LawTitle("Bộ luật Dân sự", "2015", ("đặt cọc", "thuê nhà"), "91/2015/QH13")
_CIVIL_GENERAL = _LawTitle(
    "Bộ luật Dân sự",
    "2015",
    ("hợp đồng", "vay", "thừa kế", "ranh giới", "bồi thường", "chiếm giữ", "lừa dối"),
    "91/2015/QH13",
    legal_types=("luat", "bo luat"),
    exact_title_only=False,
    domain_rules=(
        (r"thuc tap|thoa thuan|hop dong", ("khai niem hop dong", "hinh thuc cua hop dong", "giao dich dan su", "thuc hien hop dong")),
        (r"chu ky|zalo|thong diep|dien tu", ("hinh thuc giao dich dan su", "phuong tien dien tu", "giao dich dien tu")),
        (r"vay|muon tien|khong giay to|khong tra", ("hop dong vay tai san", "nghia vu tra no", "hinh thuc giao dich dan su", "bang loi noi", "thoi hieu khoi kien")),
        (r"cho (?:.*\s)?vay|vay .* khong giay to|khong lap thanh van ban|doi no", ("thoi hieu khoi kien ve hop dong", "03 nam")),
        (r"lan sang dat|ranh gioi|hang xom", ("ranh gioi giua cac bat dong san", "nghia vu ton trong quy tac xay dung", "lan chiem")),
        (r"thua ke|di chuc|cha me|anh em", ("thua ke theo phap luat", "nguoi thua ke theo phap luat", "hang thua ke thu nhat", "phan chia di san")),
        (r"danh roi|bo quen|chiem giu", ("xac lap quyen so huu doi voi tai san do nguoi khac danh roi", "tai san bi danh roi, bo quen", "chi dinh chu so huu")),
        (r"lua mat tien|bi lua|lua doi", ("giao dich dan su vo hieu do bi lua doi", "hoan tra cho nhau nhung gi da nhan", "boi thuong thiet hai")),
        (r"mieng|bang van ban|bang loi noi|hinh thuc|co gia tri phap ly", ("hinh thuc giao dich dan su", "giao dich dan su duoc the hien bang loi noi bang van ban hoac bang hanh vi cu the")),
        (r"thoi hieu|het bao nhieu nam|khong con duoc kien|bao lau ke tu|thoi han de khoi kien|may nam|bao nhieu nam", ("thoi hieu khoi kien ve hop dong", "03 nam")),
        (r"vo hieu|cong chung|chung thuc|khong cong chung", ("vi pham quy dinh bat buoc ve cong chung", "hai phan ba nghia vu")),
    ),
)
_CIVIL_PROC = _LawTitle(
    "Bộ luật Tố tụng dân sự",
    "2015",
    ("chứng cứ", "khởi kiện", "hồ sơ khởi kiện"),
    "92/2015/QH13",
    legal_types=("luat", "bo luat"),
    exact_title_only=False,
    domain_rules=(
        (r"tin nhan|zalo|chung cu|du lieu dien tu|scan", ("nguon chung cu", "du lieu dien tu", "thong diep du lieu", "xac dinh chung cu")),
        (r"kien|khoi kien|toa an|tranh chap", ("quyen khoi kien vu an", "don khoi kien", "tham quyen cua toa an", "nguon chung cu")),
        (r"ho so|giay to|tai lieu|don khoi kien", ("danh muc tai lieu",)),
        (r"hoa giai|doi no|kien doi no|don kien|kien ra toa|yeu cau hoa giai|bat buoc hoa giai|phai hoa giai", ("hoa giai trong tung dan su", "nguyen tac tien hanh hoa giai", "trong thoi han chuan bi xet xu")),
    ),
)
_MARRIAGE = _LawTitle(
    "Luật Hôn nhân và gia đình",
    "2014",
    ("ly hôn", "kết hôn", "nuôi con", "ngoại tình"),
    "52/2014/QH13",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"nuoi con|ly hon|ngoai tinh", ("duoi 36 thang tuoi", "quyen yeu cau giai quyet ly hon", "ly hon theo yeu cau cua mot ben", "vo chong thuong chung")),
        (r"2 tuoi|36 thang|duoi 3 tuoi|con nho|nuoi con|ngoai tinh", ("duoi 36 thang tuoi", "giao cho me truc tiep nuoi")),
        (r"tai san chung|mua sau khi cuoi|dung ten .* chong|chia tai san", ("tai san chung cua vo chong", "nguyen tac giai quyet tai san cua vo chong khi ly hon", "thoi ky hon nhan")),
        (r"ket hon", ("dieu kien ket hon", "dang ky ket hon")),
    ),
)
_CIVIL_STATUS = _LawTitle(
    "Luật Hộ tịch",
    "2014",
    ("kết hôn",),
    "60/2014/QH13",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"ket hon|vang mat", ("thu tuc dang ky ket hon", "hai ben nam, nu phai co mat", "tham quyen dang ky ket hon")),
    ),
)
_DOMESTIC_VIOLENCE = _LawTitle(
    "Luật Phòng, chống bạo lực gia đình",
    "2022",
    ("bạo lực gia đình",),
    "13/2022/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"bao hanh|danh dap|bao luc|cong an", ("bao tin, to giac ve hanh vi bao luc gia dinh", "cam tiep xuc", "ngan chan", "cong an xa")),
    ),
)
_LAND = _LawTitle(
    "Luật Đất đai",
    "2024",
    ("quyền sử dụng đất", "chuyển nhượng đất", "tranh chấp đất", "mua bán đất", "công chứng"),
    "31/2024/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"khong co giay to|so do|giay chung nhan|chuyen quyen su dung dat", ("cap giay chung nhan", "khong co giay to ve quyen su dung dat", "truoc ngay 01 thang 7 nam 2014", "chuyen quyen su dung dat")),
        (r"thu hoi dat|den bu|boi thuong|gia thi truong", ("nguyen tac boi thuong", "nguyen tac, can cu, phuong phap dinh gia dat", "nguyen tac thi truong", "gia dat cu the", "bang gia dat")),
        (r"tach thua|dat nong nghiep|sang ten", ("tach thua dat, hop thua dat", "dieu kien tach thua", "dang ky bien dong")),
        (r"lan sang dat|tranh chap|hoa giai", ("hoa giai tranh chap dat dai", "tham quyen giai quyet tranh chap dat dai")),
        (r"cong chung|mua ban dat|vo hieu|chuyen nhuong dat", ("phai duoc cong chung hoac chung thuc",)),
    ),
)
_TRAFFIC_DECREE = _LawTitle(
    "Nghị định 168/2024/NĐ-CP",
    "2024",
    ("nồng độ cồn", "đèn tín hiệu", "giao thông"),
    "168/2024/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"nong do con|uong ruou|uong bia|say xin|say ruou|bia ruou|ruou bia", ("nong do con", "xe mo to, xe gan may", "0,25 miligam", "0,4 miligam", "diem cua giay phep lai xe")),
        (r"den tin hieu|vuot den", ("khong chap hanh hieu lenh cua den tin hieu giao thong", "bi tru diem giay phep lai xe 04 diem", "diem b, diem c, diem d khoan 9", "diem c, diem d, diem d khoan 7", "4.000.000 dong den 6.000.000 dong", "18.000.000 dong")),
        (r"dang ky xe|sang ten|chuyen quyen so huu|dung xe", ("khong lam thu tuc cap chung nhan dang ky xe", "chuyen quyen so huu", "thu tuc xu phat", "xac minh")),
        (r"nguoi di bo|vuot au", ("xu phat nguoi di bo", "150.000 dong", "400.000 dong")),
    ),
)
_TRAFFIC_LAW = _LawTitle(
    "Luật Trật tự, an toàn giao thông đường bộ",
    "2024",
    ("giao thông",),
    "36/2024/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"dung xe|kiem soat|csgt|canh sat giao thong", ("dung phuong tien", "tuan tra, kiem soat", "giay chung nhan dang ky xe")),
        (r"diem|nong do con|den tin hieu", ("diem cua giay phep lai xe", "nong do con")),
    ),
)
_SOCIAL_INSURANCE = _LawTitle(
    "Luật Bảo hiểm xã hội",
    "2024",
    ("bảo hiểm xã hội", "lương hưu"),
    "41/2024/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"1 lan|mot lan", ("huong bao hiem xa hoi mot lan", "sau 12 thang", "chua du 20 nam", "muc huong bao hiem xa hoi mot lan")),
        (r"luong huu|bao nhieu nam|so nam|du nam|dong bao hiem", ("tu du 20 nam", "huong luong huu")),
        (r"bat buoc|doi tuong|thuc tap|khong ky hop dong|hop dong lao dong|dong bao hiem", ("doi tuong tham gia bao hiem xa hoi bat buoc", "hop dong lao dong khong xac dinh thoi han")),
    ),
)
_PIT_2025 = _LawTitle(
    "Luật Thuế thu nhập cá nhân",
    "2025",
    ("thuế thu nhập cá nhân",),
    "109/2025/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"doanh thu|ban hang|online|shopee|kinh doanh", ("thu nhap tu kinh doanh", "500 trieu dong tro xuong khong phai nop thue", "ky tinh thue nam 2026")),
        (r"luong|giam tru|phu thuoc|con nho|bieu thue", ("thu nhap tu tien luong, tien cong", "bieu thue luy tien tung phan", "giam tru gia cảnh", "giam tru gia canh", "dieu khoan thi hanh")),
    ),
)
_PIT_RELIEF_2025 = _LawTitle(
    "Nghị quyết 110/2025/UBTVQH15",
    "2025",
    ("thuế thu nhập cá nhân",),
    "110/2025/UBTVQH15",
    legal_types=("nghi quyet",),
    exact_title_only=False,
    domain_rules=(
        (r"thue|giam tru|luong|con nho|phu thuoc", ("15,5 trieu", "6,2 trieu", "nguoi phu thuoc")),
    ),
)
_HOUSEHOLD_TAX_2026 = _LawTitle(
    "Nghị định 68/2026/NĐ-CP",
    "2026",
    ("thuế thu nhập cá nhân",),
    "68/2026/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"doanh thu|ban hang|online|shopee|ho kinh doanh", ("500 trieu", "thuong mai dien tu", "thue gia tri gia tang", "thue thu nhap ca nhan")),
    ),
)
_ENTERPRISE = _LawTitle(
    "Luật Doanh nghiệp",
    "2020",
    ("đăng ký kinh doanh",),
    "59/2020/QH14",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"von dieu le|tnhh|trach nhiem huu han|thanh lap", ("von dieu le", "cong ty trach nhiem huu han mot thanh vien", "trong pham vi so von gop")),
        (r"no luong|co dong|giam doc|trach nhiem", ("nguoi dai dien theo phap luat", "trach nhiem cua nguoi dai dien", "co dong chi chiu trach nhiem ve cac khoan no", "pham vi so von da gop")),
    ),
)
_E_TRANSACTION = _LawTitle(
    "Văn bản hợp nhất 42/VBHN-VPQH",
    "2025",
    ("chữ ký điện tử",),
    "42/VBHN-VPQH",
    legal_types=("van ban hop nhat",),
    exact_title_only=False,
    domain_rules=(
        (r"chu ky|scan|thong diep|zalo|gia tri phap ly", ("gia tri phap ly cua thong diep du lieu", "chu ky dien tu", "gia tri phap ly cua chu ky dien tu", "lam chung cu")),
    ),
)
_CONSUMER = _LawTitle(
    "Luật Bảo vệ quyền lợi người tiêu dùng",
    "2023",
    ("người tiêu dùng",),
    "19/2023/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"doi tra|hoan tien|khieu nai|hang bi loi", ("quyen cua nguoi tieu dung", "giai quyet tranh chap", "thuong luong", "hoa giai", "co quan quan ly nha nuoc")),
        (r"niem yet gia|phu thu|tinh tien", ("cung cap thong tin", "trach nhiem cua to chuc, ca nhan kinh doanh", "niem yet gia")),
    ),
)
_PRICE = _LawTitle(
    "Luật Giá",
    "2023",
    ("niêm yết giá",),
    "16/2023/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"niem yet gia|phu thu|tinh tien", ("niem yet gia", "ban cao hon gia niem yet", "cong khai ve gia")),
    ),
)
_CRIMINAL = _LawTitle(
    "Bộ luật Hình sự",
    "2015",
    ("hình sự",),
    "100/2015/QH13",
    legal_types=("luat", "bo luat"),
    exact_title_only=False,
    domain_rules=(
        (r"chiem giu|danh roi|bo quen|dem ban", ("toi chiem giu trai phep tai san", "tu 10.000.000 dong tro len")),
        (r"chui boi|xuc pham|lam nhuc|vu khong|tung anh", ("toi lam nhuc nguoi khac", "toi vu khong", "xuc pham nghiem trong nhan pham")),
        (r"lua mat tien|bi lua|lua dao", ("toi lua dao chiem doat tai san",)),
        (r"bao hanh|danh dap", ("toi nguoc dai hoac hanh ha", "toi co y gay thuong tich")),
    ),
)
_CRIMINAL_PROC = _LawTitle(
    "Bộ luật Tố tụng hình sự",
    "2015",
    ("tạm giam", "tố giác"),
    "101/2015/QH13",
    legal_types=("luat", "bo luat"),
    exact_title_only=False,
    domain_rules=(
        (r"tam giam|bat tam giam", ("dieu 119. tam giam", "ap dung bien phap tam giam")),
        (r"lua|bao hanh|bao cong an|to giac", ("to giac, tin bao ve toi pham", "trach nhiem tiep nhan va tham quyen giai quyet to giac")),
    ),
)
_CYBER_DECREE = _LawTitle(
    "Nghị định 15/2020/NĐ-CP",
    "2020",
    ("mạng xã hội",),
    "15/2020/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"mang|xuc pham|vu khong|tung anh|chui boi", ("trach nhiem su dung dich vu mang xa hoi", "thong tin sai su that", "xuc pham uy tin")),
    ),
)
_CYBER_AMEND = _LawTitle(
    "Nghị định 14/2022/NĐ-CP",
    "2022",
    ("mạng xã hội",),
    "14/2022/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"mang|xuc pham|vu khong|tung anh", ("dieu 101", "xuc pham uy tin")),
    ),
)
_ANTT_DECREE = _LawTitle(
    "Nghị định 282/2025/NĐ-CP",
    "2025",
    ("xử phạt vi phạm",),
    "282/2025/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"chiem giu|danh roi|bo quen|dem ban", ("chiem giu trai phep tai san", "xam pham tai san")),
        (r"bao hanh|danh dap|bao luc", ("hanh vi bao luc gia dinh", "danh dap")),
    ),
)
_ID_LAW = _LawTitle(
    "Luật Căn cước",
    "2023",
    ("căn cước",),
    "26/2023/QH15",
    legal_types=("luat",),
    exact_title_only=False,
    domain_rules=(
        (r"can cuoc|mat|cap lai|thoi han|o tinh khac", ("thoi han cap, cap doi, cap lai the can cuoc", "07 ngay lam viec", "noi lam thu tuc", "noi cong dan cu tru")),
    ),
)
_ID_DECREE = _LawTitle(
    "Nghị định 70/2024/NĐ-CP",
    "2024",
    ("căn cước",),
    "70/2024/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"online|cong dich vu cong|cap lai|tam tru", ("cong dich vu cong quoc gia", "truc tuyen", "cap lai the can cuoc")),
    ),
)
_LABOR_PENALTY = _LawTitle(
    "Nghị định 12/2022/NĐ-CP",
    "2022",
    ("tiền lương", "bảo hiểm xã hội"),
    "12/2022/NĐ-CP",
    legal_types=("nghi dinh",),
    exact_title_only=False,
    domain_rules=(
        (r"no luong|giu luong|tra luong|so bao hiem", ("tra luong khong dung han", "buoc nguoi su dung lao dong tra du tien luong", "vi pham quy dinh ve tien luong")),
    ),
)


def _active_turn_text(query: str) -> str:
    marker = "Câu hỏi mới (ưu tiên dữ kiện mới):"
    text = str(query or "")
    if marker in text:
        return text.split(marker, 1)[1].strip()
    return text


def _planned_titles(query: str, *, max_docs: int = _MAX_DOCUMENT_LOADS) -> tuple[_LawTitle, ...]:
    normalized = normalize_colloquial_query(query)
    active = normalize_colloquial_query(_active_turn_text(query))
    folded = fold_topic_text(normalized)
    folded_active = fold_topic_text(active)
    topics = set(extract_official_topic_phrases(normalized, limit=6))
    selected: list[_LawTitle] = []

    def add(law: _LawTitle) -> None:
        if law not in selected:
            selected.append(law)

    # Tax & Social Insurance (use diacritics / explicit tax phrases so "thuê nhà" never collides with "thuế")
    raw_lower = str(normalized or "").casefold()
    tax_match = bool(
        re.search(
            r"\b(?:thuế thu nhập cá nhân|giảm trừ gia cảnh|người phụ thuộc|đóng thuế|nộp thuế|bán hàng online|shopee)\b",
            raw_lower,
        )
        or (
            re.search(r"\bthuế\b", raw_lower)
            and re.search(r"\b(?:thu nhap|luong|con nho|doanh thu|ban hang|kinh doanh)\b", folded)
        )
        or re.search(r"\b(?:thue tncn|giam tru gia canh|nguoi phu thuoc|nop thue|dong thue|doanh thu .* ban hang)\b", folded)
    )
    if tax_match:
        add(_PIT_2025)
        add(_PIT_RELIEF_2025)
        if re.search(r"\b(?:ban hang|online|shopee|doanh thu|kinh doanh)\b", folded):
            add(_HOUSEHOLD_TAX_2026)

    if re.search(r"\b(?:rut .* (?:bao hiem xa hoi|1 lan|mot lan)|bao hiem xa hoi .* (?:1 lan|mot lan))\b", folded):
        add(_SOCIAL_INSURANCE)
    if re.search(r"\b(?:luong huu|bao hiem xa hoi)\b", folded) and re.search(r"\b(?:bao nhieu nam|du nam|so nam|bao lau|dong du)\b", folded):
        add(_SOCIAL_INSURANCE)

    # Preserve exact test boundary: registration for business household is Enterprise/Tax, not Labor.
    if (not tax_match and topics.intersection(_LABOR.topics)) or re.search(
        r"\b(?:thuc tap|tro cap thuc tap|nghi viec|duoi viec|duoi ngang|giu luong|no luong|so bao hiem|part[- ]?time|khong ky hop dong|don phuong cham dut|sa thai|tro cap thoi viec|tro cap mat viec|nghi phep|nghi hang nam|hdld|mat viec|bi cho nghi|khong xac dinh thoi han|xin nghi|muon nghi|nghi phai|nhan vien|ngay phep|phep nam)\b",
        folded,
    ):
        add(_LABOR)
        if "thử việc" not in topics:
            if re.search(r"\b(?:co dong|giam doc|nguoi dai dien)\b", folded) and re.search(r"\b(?:no luong|trach nhiem)\b", folded):
                add(_ENTERPRISE)
            if re.search(r"\b(?:no luong|giu luong|so bao hiem|duoi ngang|thanh tra|khoi kien|di dau kien)\b", folded):
                add(_LABOR_PENALTY)
            if re.search(r"\b(?:thuc tap|tro cap)\b", folded):
                add(_CIVIL_GENERAL)

    if re.search(r"\b(?:hoa giai|tranh chap)\b", folded) and re.search(
        r"\b(?:cong ty|nguoi lao dong|nguoi su dung|luong|tien ho tro|cat tien|cam ket)\b", folded
    ):
        add(_LABOR)

    if "đặt cọc" in topics:
        add(_CIVIL)

    # Civil follow-ups (e.g. Zalo evidence for a loan dispute) prioritize Civil Procedure
    if re.search(r"\b(?:tin nhan|zalo|chung cu|du lieu dien tu|khoi kien|di kien|kien doi|kien ra toa|don kien|hoa giai|doi no|yeu cau hoa giai|bat buoc hoa giai)\b", folded_active):
        add(_CIVIL_PROC)
    if re.search(r"\b(?:cho .* vay|muon tien|vay .* khong giay to|khong tra|tien coc|hop dong|thua ke|di chuc|lan sang dat|ranh gioi|lua mat tien)\b", folded):
        if re.search(r"\b(?:lua mat tien|bi lua|lua dao|chiem doat)\b", folded):
            add(_CRIMINAL)
            add(_CRIMINAL_PROC)
        add(_CIVIL_GENERAL)
        if re.search(r"\b(?:vay|muon|khoi kien|kien duoc|chung cu|tranh chap)\b", folded):
            add(_CIVIL_PROC)
    # Limitation periods and debt recovery belong to the Civil Code (contract claims), not only CPC.
    if re.search(
        r"\b(?:thoi hieu|doi no|no vay|vay tai san|het bao nhieu nam|khong con duoc kien|bao lau ke tu|"
        r"thoi han de khoi kien|thoa thuan|bang mieng|bang loi noi|bang van ban|lap thanh van ban|"
        r"gia tri phap ly|hinh thuc)\b",
        folded,
    ):
        add(_CIVIL_GENERAL)

    # Marriage, divorce, custody, property, domestic violence, civil registration
    if re.search(r"\b(?:ly hon|ngoai tinh|nuoi con|mua sau khi cuoi|dung ten .* chong|tai san chung|ket hon)\b", folded):
        add(_MARRIAGE)
        if re.search(r"\b(?:ket hon|vang mat|xuat khau lao dong)\b", folded):
            add(_CIVIL_STATUS)
    if re.search(r"\b(?:bao hanh|danh dap|bao luc gia dinh|bat tam giam)\b", folded):
        add(_DOMESTIC_VIOLENCE)
        add(_CRIMINAL_PROC)
        add(_CRIMINAL)
        add(_ANTT_DECREE)

    if re.search(r"\b(?:mua ban dat|chuyen nhuong (?:quyen su dung )?dat)\b", folded):
        add(_LAND)

    # Exclude bare "sang ten" for vehicles (e.g., xe máy không chính chủ -> Traffic, not Land)
    if (
        re.search(r"\b(?:giay tay|so do|giay chung nhan|dat nong nghiep|thu hoi dat|den bu|gia thi truong|lan sang dat|tach thua)\b", folded)
        or (re.search(r"\bboi thuong\b", folded) and re.search(r"\b(?:dat|thua dat|nha o|bat dong san|thu hoi)\b", folded))
        or (
            "sang ten" in folded
            and not re.search(r"\b(?:xe mo to|xe gan may|o to|phuong tien|csgt|canh sat giao thong)\b", folded)
        )
    ):
        add(_LAND)
        if re.search(r"\b(?:thua ke|di chuc|anh em|cha me)\b", folded):
            add(_CIVIL_GENERAL)

    # Traffic (vehicles, alcohol, red light, unregistered owner, pedestrian)
    if re.search(r"\b(?:nong do con|vuot den do|bang lai|giay phep lai xe|xe may|xe mo to|xe gan may|o to|khong chinh chu|csgt|canh sat giao thong|nguoi di bo|vuot au|dung xe|say xin|say ruou|uong ruou|uong bia|bia ruou|ruou bia)\b", folded):
        add(_TRAFFIC_DECREE)
        add(_TRAFFIC_LAW)

    # Enterprise & E-signature
    if re.search(r"\b(?:trach nhiem huu han|tnhh|von dieu le|dang ky kinh doanh|thanh lap cong ty|co dong)\b", folded):
        add(_ENTERPRISE)
    if re.search(r"\b(?:chu ky scan|chu ky dien tu|chup anh gui zalo|thong diep du lieu)\b", folded):
        add(_E_TRANSACTION)
        add(_CIVIL_PROC)

    # Consumer protection & pricing
    if re.search(r"\b(?:mua .* online|hang bi loi|doi tra|hoan tien|niem yet gia|phu thu|quan an|nguoi tieu dung)\b", folded):
        add(_CONSUMER)
        if re.search(r"\b(?:niem yet gia|phu thu|tinh tien)\b", folded):
            add(_PRICE)

    # Minor criminal, cyber harassment, lost property
    if re.search(r"\b(?:boc phot|tung anh|chui boi|xuc pham|lam nhuc|vu khong|mang xa hoi|nhat duoc|dem ban)\b", folded):
        add(_CRIMINAL)
        if re.search(r"\b(?:boc phot|tung anh|tren mang|chui boi)\b", folded):
            add(_CYBER_DECREE)
            add(_CYBER_AMEND)
        else:
            add(_CIVIL_GENERAL)
            add(_ANTT_DECREE)

    # National ID card
    if re.search(r"\b(?:can cuoc|lam lai .* o tinh khac|thuong tru|tam tru)\b", folded):
        add(_ID_LAW)
        add(_ID_DECREE)

    return tuple(selected[:max(1, max_docs)])


def _is_explicitly_scoped(query: str, titles: tuple[_LawTitle, ...]) -> bool:
    """Reject a different named law; dates and article references remain usable."""
    folded = fold_topic_text(query)
    allowed_numbers = {_number_key(title.document_number) for title in titles}
    if any(_number_key(match.group()) not in allowed_numbers
           for match in _DOCUMENT_ID.finditer(folded)):
        return True
    for match in re.finditer(r"\b(?:bo )?luat\b", folded):
        if re.search(r"(?:phap|pham|trai|dung|sai|vi|hieu|mat)\s+$", folded[:match.start()]):
            continue
        remainder = folded[match.end():].strip()
        if re.match(
            r"(?:nay|moi(?:\s+nhat)?|hien hanh|hien nay|hien tai|viet nam|khac|co lien quan|quy dinh|ve|co|khong|nhu|thi|la|ap dung)\b|\d",
            remainder,
        ) or not remainder:
            continue
        named = folded[match.start():]
        target = next((title for title in titles
                       if re.match(re.escape(fold_topic_text(title.title_base)) + r"\b", named)), None)
        if target is None:
            return True
        tail = named[len(fold_topic_text(target.title_base)):].strip()
        year = re.match(
            r"(?:\(\s*)?(?:(?:duoc\s+)?ban hanh\s+(?:vao\s+)?)?(?:nam\s+)?((?:19|20)\d{2})\b",
            tail,
        )
        if year and year.group(1) != target.year:
            return True
    return False


def _number_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _contains_topic_phrase(text: str, topic: str) -> bool:
    return contains_topic_phrase(text, topic)


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _issuance_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _rescue_browser(settings: Any, browser: Any | None) -> Any:
    if browser is not None:
        return browser
    from app.services.legal_browser import (
        ContentStore,
        LegalBrowser,
        LegalFtsIndex,
        local_legal_index_ready,
    )

    if not getattr(settings, "SERVERLESS_ONLINE_ONLY", False):
        full_content = getattr(settings, "CONTENT_STORE_PATH", None)
        full_fts = getattr(settings, "LEGAL_FTS_PATH", None)
        if (
            full_content is not None
            and full_fts is not None
            and local_legal_index_ready(settings, full_content, full_fts)
        ):
            store = ContentStore(full_content)
            return LegalBrowser(
                store=store,
                index=LegalFtsIndex(
                    store=store,
                    path=full_fts,
                    dataset_revision=getattr(settings, "DATASET_REVISION", ""),
                ),
            )
    return LegalBrowser.from_settings(settings)


def _search_and_load(
    query: str,
    planned_titles: tuple[_LawTitle, ...],
    settings: Any,
    browser: Any | None,
    deadline: float,
    *,
    max_documents_override: int | None = None,
    max_evidence_override: int | None = None,
    max_tokens_override: int | None = None,
) -> tuple[list[EvidenceChunk], dict[str, Any]]:
    from app.services.legal_browser import LegalBrowser

    diagnostics: dict[str, Any] = {
        "status": "no_evidence",
        "method": "curated_primary_law_title_metadata_v1",
        "provenance": "pinned_corpus_store",
        "legal_effect_asserted": False,
        "current_effect_status": "unverified",
        "title_searches": [],
        "candidates": 0,
        "corpus_documents_loaded": 0,
        "corpus_document_load_attempts": 0,
        "selected_chunk_count": 0,
    }
    if time.monotonic() >= deadline:
        diagnostics["status"] = "timeout"
        return [], diagnostics
    try:
        selected_browser = _rescue_browser(settings, browser)
    except Exception as error:
        diagnostics.update(status="unavailable", error_type=type(error).__name__)
        return [], diagnostics

    normalized_query = normalize_colloquial_query(query)
    active_normalized = normalize_colloquial_query(_active_turn_text(query))
    folded_active_query = fold_topic_text(active_normalized)
    max_documents = max(1, int(max_documents_override or _MAX_DOCUMENT_LOADS))
    loaded = 0
    chunks_with_scores: list[
        tuple[int, int, int, int, int, frozenset[str], EvidenceChunk]
    ] = []
    query_topics = extract_official_topic_phrases(normalized_query, limit=6)
    query_terms = set(local_rescue_terms(normalized_query, limit=18))
    active_terms = set(local_rescue_terms(active_normalized, limit=14))
    rental_deposit = "đặt cọc" in query_topics and "thuê nhà" in query_topics
    handover = bool(re.search(r"\b(?:ban giao|tra lai|hoan tra)\b", fold_topic_text(normalized_query)))
    trial_facets = _trial_facets(normalized_query)
    requested_articles = [
        (int(first), int(last or first))
        for first, last in _ARTICLE_REFERENCE.findall(fold_topic_text(normalized_query))
    ]
    requested_clauses = set(re.findall(r"\bkhoan\s+(\d+)\b", fold_topic_text(normalized_query)))
    now = datetime.now(timezone.utc).date()

    for target_index, target in enumerate(planned_titles):
        item: dict[str, Any] = {
            "title_query": target.exact_title if target.exact_title_only else target.document_number,
            "expected_title": target.exact_title,
            "status": "not_found",
        }
        diagnostics["title_searches"].append(item)
        if time.monotonic() >= deadline:
            diagnostics["status"] = "timeout"
            break
        search_limit = _MAX_TITLE_CANDIDATES if target.exact_title_only else 25
        try:
            results = list(selected_browser.search(
                item["title_query"],
                limit=search_limit,
            ) or ())[:search_limit]
        except Exception as error:
            item.update(status="search_error", error_type=type(error).__name__)
            diagnostics["status"] = "search_error"
            continue
        if time.monotonic() >= deadline:
            diagnostics["status"] = "timeout"
            break

        diagnostics["candidates"] += len(results)
        eligible: list[tuple[date, Any, int]] = []
        allowed_types = {fold_topic_text(t) for t in target.legal_types}
        for result in results:
            title = str(_field(result, "title", "") or "").strip()
            folded_title = fold_topic_text(title)
            if target.exact_title_only:
                if folded_title != fold_topic_text(target.exact_title):
                    item["status"] = "title_mismatch"
                    continue
            else:
                if _number_key(_field(result, "document_number")) != _number_key(target.document_number):
                    item["status"] = "document_number_mismatch"
                    continue
                if not folded_title.startswith(fold_topic_text(target.title_base)):
                    item["status"] = "title_mismatch"
                    continue
                if any(fold_topic_text(ex) in folded_title for ex in target.title_exclude):
                    continue
            if fold_topic_text(_field(result, "legal_type", "")) not in allowed_types:
                item["status"] = "legal_type_mismatch"
                continue
            issued = _issuance_date(_field(result, "issuance_date"))
            if issued is None:
                item["status"] = "invalid_issuance_date"
                continue
            if issued > now:
                item["status"] = "future_issuance_date"
                continue
            try:
                document_id = int(_field(result, "document_id"))
            except (TypeError, ValueError):
                item["status"] = "invalid_document_id"
                continue
            if document_id <= 0:
                item["status"] = "invalid_document_id"
                continue
            eligible.append((issued, result, document_id))

        if not eligible:
            continue
        # Issue date orders duplicates; it does not establish legal effect.
        eligible.sort(key=lambda candidate: (candidate[0], -candidate[2]), reverse=True)
        issued, selected, document_id = eligible[0]
        if loaded >= max_documents or time.monotonic() >= deadline:
            diagnostics["status"] = "timeout" if time.monotonic() >= deadline else "load_limit"
            break
        loaded += 1
        diagnostics["corpus_document_load_attempts"] = loaded
        try:
            document = selected_browser.get_document(document_id)
        except Exception as error:
            item.update(status="load_error", error_type=type(error).__name__)
            diagnostics["status"] = "load_error"
            continue
        if document is None:
            item["status"] = "document_missing"
            diagnostics["status"] = "integrity_error"
            continue
        metadata = _field(document, "metadata")
        content = _field(document, "content")
        try:
            stored_id = int(_field(metadata, "document_id"))
        except (TypeError, ValueError):
            stored_id = -1
        metadata_title = str(_field(metadata, "title", "") or "").strip()
        folded_meta_title = fold_topic_text(metadata_title)
        metadata_number = _field(metadata, "document_number")
        hit_number = _field(selected, "document_number")
        metadata_date = _issuance_date(_field(metadata, "issuance_date"))
        title_ok = (
            folded_meta_title == fold_topic_text(target.exact_title)
            if target.exact_title_only
            else folded_meta_title.startswith(fold_topic_text(target.title_base))
            and _number_key(metadata_number) == _number_key(target.document_number)
        )
        if (
            stored_id != document_id
            or not _number_key(hit_number)
            or _number_key(metadata_number) != _number_key(hit_number)
            or not title_ok
            or fold_topic_text(_field(metadata, "legal_type", "")) not in allowed_types
            or metadata_date != issued
            or metadata_date is None
            or metadata_date > now
            or not isinstance(content, str)
            or not content.strip()
        ):
            item["status"] = "metadata_integrity_error"
            diagnostics["status"] = "integrity_error"
            continue
        actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stored_digest = str(_field(document, "content_sha256", "") or "").casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", stored_digest) or actual_digest != stored_digest:
            item["status"] = "content_hash_mismatch"
            diagnostics["status"] = "integrity_error"
            continue

        if not assess_source_quality(content)["usable_as_evidence"]:
            item["status"] = "source_quality_rejected"
            diagnostics["status"] = "source_quality_rejected"
            continue

        target_topics = tuple(topic for topic in target.topics if topic in query_topics)
        token_cap = max_tokens_override if max_tokens_override is not None else _MAX_CONTEXT_TOKENS
        max_tokens = min(
            token_cap,
            max(1, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", token_cap)))
            if max_tokens_override is None
            else token_cap,
        )
        chunk_max = max(1, int(getattr(settings, "QUERY_CHUNK_MAX_TOKENS", 220)))
        overlap = max(0, int(getattr(settings, "QUERY_CHUNK_OVERLAP_TOKENS", 24)))
        preserve_unit_max_tokens = min(480 if max_tokens_override is None else 700, max(1, max_tokens - 80))
        effective_chunk_max = chunk_max if max_tokens_override is None else max(chunk_max, 420)
        preserve_article_max_tokens = (
            preserve_unit_max_tokens
            if not requested_clauses and max_tokens_override is None
            else None
        )
        group_counts, prepared_chunks = _prepared_chunks_for_document(
            document_id=document_id,
            actual_digest=actual_digest,
            metadata=metadata,
            content=content,
            preserve_unit_max_tokens=preserve_unit_max_tokens,
            preserve_article_max_tokens=preserve_article_max_tokens,
            require_preamble=not bool(requested_articles),
            chunk_max=effective_chunk_max,
            overlap=overlap,
        )
        strict_trial_only = target == _LABOR and "thử việc" in query_topics
        for position, (chunk, folded_chunk, body) in enumerate(prepared_chunks):
            if requested_articles:
                article = _ARTICLE_REFERENCE.search(fold_topic_text(chunk.article or ""))
                if article is None or not any(
                    first <= int(article.group(1)) <= last for first, last in requested_articles
                ):
                    continue
            if requested_clauses and str(chunk.clause) not in requested_clauses:
                continue
            # Preserve existing behavior for _LABOR/_CIVIL mocks; allow opening window of long clauses for large budget rescue.
            if group_counts[(chunk.article, chunk.clause)] > 1:
                if max_tokens_override is None or strict_trial_only:
                    continue
                if position > 0 and prepared_chunks[position - 1][0].article == chunk.article and prepared_chunks[position - 1][0].clause == chunk.clause:
                    continue
            if (
                strict_trial_only
                and not _contains_topic_phrase(chunk.text, "thử việc")
            ):
                continue
            supported = [
                topic
                for topic in target_topics
                if _contains_topic_phrase(chunk.text, topic)
                and matches_legal_situation(normalized_query, chunk.text)
            ]
            if target == _LABOR and trial_facets:
                facet_patterns = {
                    "trial_duration": r"\bthoi gian thu viec\b",
                    "trial_wage": r"\btien luong thu viec\b",
                    "trial_termination": r"\b(?:khong can bao truoc|huy bo hop dong)\b",
                }
                supported.extend(facet for facet in trial_facets
                                 if re.search(facet_patterns[facet], folded_chunk))
            if target == _CIVIL and rental_deposit:
                if (
                    "hop dong thue nha" in folded_chunk
                    and _contains_topic_phrase(chunk.text, "thuê nhà")
                    and "thuê nhà" not in supported
                ):
                    supported.append("thuê nhà")
                if (
                    handover
                    and re.search(r"^dieu\s+\d+\.\s+tra lai tai san thue\b", folded_chunk)
                    and "ben thue" in folded_chunk
                ):
                    supported.append("bàn giao")
            domain_hits = 0
            if not strict_trial_only:
                folded_norm = fold_topic_text(normalized_query)
                rule_matched_any = False
                for q_pat, phrases in target.domain_rules:
                    if re.search(q_pat, folded_norm):
                        for phrase in phrases:
                            fp = fold_topic_text(phrase)
                            if fp and fp in folded_chunk:
                                supported.append(f"rule:{fp}")
                                domain_hits += 4
                                rule_matched_any = True
                if target == _LABOR and not rule_matched_any and not target_topics:
                    for phrase in ("hop dong lao dong", "don phuong cham dut", "thanh toan day du", "hoa giai vien lao dong", "toa an nhan dan"):
                        if phrase in folded_chunk:
                            supported.append(f"kw:{phrase}")
                            domain_hits += 1
                elif target != _LABOR and target != _CIVIL and not rule_matched_any and not target.domain_rules:
                    overlap_active = len(active_terms.intersection(body))
                    if overlap_active >= 2 and matches_legal_situation(normalized_query, chunk.text):
                        supported.append(f"act:{overlap_active}")
            if not supported:
                continue
            overlap_score = len(query_terms.intersection(body)) + len(active_terms.intersection(body)) + domain_hits
            heading_score = _heading_phrase_overlap(normalized_query, chunk.text) + _heading_phrase_overlap(active_normalized, chunk.text)
            keyword_only = int(_is_keyword_only_clause(chunk.text))
            verified = replace(chunk, source_content_sha256=actual_digest)
            chunks_with_scores.append(
                (-len(supported), keyword_only, -heading_score, -overlap_score,
                 (target_index, position), frozenset(supported), verified)
            )
        item.update(status="body_verified", document_loaded=True)
        diagnostics["corpus_documents_loaded"] += 1

    ev_cap = max_evidence_override if max_evidence_override is not None else _MAX_EVIDENCE
    tok_cap = max_tokens_override if max_tokens_override is not None else _MAX_CONTEXT_TOKENS
    max_evidence = min(
        ev_cap,
        max(0, int(getattr(settings, "FINAL_EVIDENCE_LIMIT", ev_cap)))
        if max_evidence_override is None
        else ev_cap,
    )
    max_tokens = min(
        tok_cap,
        max(0, int(getattr(settings, "LLM_CONTEXT_MAX_TOKENS", tok_cap)))
        if max_tokens_override is None
        else tok_cap,
    )
    selected_chunks: list[EvidenceChunk] = []
    used_tokens = 0
    seen: set[tuple[int, str, str]] = set()
    substantive_topics: dict[int, set[str]] = {}
    for _topic_score, keyword_only, _heading_score, _query_score, _position, topics, chunk in chunks_with_scores:
        if not keyword_only:
            substantive_topics.setdefault(chunk.document_id, set()).update(topics)
    ranked_chunks = sorted(chunks_with_scores, key=lambda item: item[:5])
    priority_facets = ("đặt cọc", "thuê nhà", "bàn giao") if rental_deposit else trial_facets
    prioritized = []
    for facet in priority_facets:
        candidates = [item for item in ranked_chunks if facet in item[5]]
        if facet == "bàn giao" and not re.search(
            r"\b(?:cham|tre)\s+(?:tra|ban giao)\b", fold_topic_text(normalized_query)
        ):
            candidates.sort(
                key=lambda item: (
                    "cham tra" in fold_topic_text(item[6].text),
                    "tinh trang" not in fold_topic_text(item[6].text),
                )
            )
        match = candidates[0] if candidates else None
        if match is not None and match not in prioritized:
            prioritized.append(match)
    if len(planned_titles) > 1 and max_evidence_override is not None:
        # Ensure balanced multi-statute representation (up to top 2 chunks per loaded statute in round-robin passes)
        per_doc_cap = 2 if max_evidence_override >= 6 else 1
        doc_counts: Counter[int] = Counter()
        for pass_num in range(1, per_doc_cap + 1):
            for item in ranked_chunks:
                doc_id = item[6].document_id
                if doc_counts[doc_id] < pass_num and item not in prioritized:
                    prioritized.append(item)
                    doc_counts[doc_id] += 1
    for _topic_score, keyword_only, _heading_score, _query_score, _position, topics, chunk in [
        *prioritized, *ranked_chunks
    ]:
        if keyword_only and topics <= substantive_topics.get(chunk.document_id, set()):
            continue
        identity = (chunk.document_id, chunk.citation, chunk.text)
        if identity in seen:
            continue
        context_cost = len(chunk.formatted_context().split())
        reference_cost = len(f"[Tài liệu tham khảo #{len(selected_chunks) + 1}]".split())
        if len(selected_chunks) >= max_evidence or used_tokens + context_cost + reference_cost > max_tokens:
            continue
        selected_chunks.append(chunk)
        seen.add(identity)
        used_tokens += context_cost + reference_cost
    diagnostics.update(
        status="evidence_selected" if selected_chunks else diagnostics["status"],
        selected_chunk_count=len(selected_chunks),
        selected_context_tokens=used_tokens,
    )
    return selected_chunks, diagnostics


async def rescue_primary_law_evidence(
    query: str,
    *,
    settings: Any,
    browser: Any | None = None,
    max_documents: int | None = None,
    max_evidence: int | None = None,
    max_tokens: int | None = None,
) -> PrimaryLawRescueResult:
    """Search only curated law titles and verify source text from the selected store."""
    doc_limit = max(1, int(max_documents or _MAX_DOCUMENT_LOADS))
    planned = _planned_titles(query, max_docs=doc_limit)
    diagnostics: dict[str, Any] = {
        "status": "not_applicable",
        "method": "curated_primary_law_title_metadata_v1",
        "provenance": "pinned_corpus_store",
        "legal_effect_asserted": False,
        "current_effect_status": "unverified",
        "title_searches": [],
        "candidates": 0,
        "corpus_documents_loaded": 0,
        "corpus_document_load_attempts": 0,
        "selected_chunk_count": 0,
    }
    if getattr(settings, "USE_LEGACY_FREE_PIPELINE", None) is not False:
        diagnostics["status"] = "bypassed_legacy_lane"
        return PrimaryLawRescueResult((), diagnostics)
    if not planned:
        return PrimaryLawRescueResult((), diagnostics)
    planned = tuple(title for title in planned if not _is_explicitly_scoped(query, (title,)))
    if not planned:
        diagnostics["status"] = "bypassed_explicit_scope"
        return PrimaryLawRescueResult((), diagnostics)

    timeout = 14.0 if max_tokens is not None else _PRIMARY_RESCUE_TIMEOUT_SECONDS
    deadline = time.monotonic() + timeout
    task = asyncio.create_task(
        asyncio.to_thread(
            _search_and_load,
            query,
            planned,
            settings,
            browser,
            deadline,
            max_documents_override=max_documents,
            max_evidence_override=max_evidence,
            max_tokens_override=max_tokens,
        )
    )
    try:
        done, _pending = await asyncio.wait(
            {task}, timeout=timeout
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    if task not in done:
        task.cancel()
        diagnostics["status"] = "timeout"
        return PrimaryLawRescueResult((), diagnostics)
    try:
        evidence, diagnostics = task.result()
    except Exception as error:
        diagnostics["status"] = "unavailable"
        diagnostics["error_type"] = type(error).__name__
        return PrimaryLawRescueResult((), diagnostics)
    return PrimaryLawRescueResult(tuple(evidence), diagnostics)


def prefer_primary_topic_contexts(
    query: str,
    corpus_contexts: list[str],
    primary_contexts: list[str],
    *,
    max_evidence: int = _MAX_EVIDENCE,
) -> list[str]:
    """Replace same-topic corpus passages with verified primary-law passages."""
    if not primary_contexts:
        return list(corpus_contexts)
    from app.services.chat_official_supplement import (
        _topic_evidence_body,
        topic_supporting_contexts,
    )

    topics = extract_official_topic_phrases(query, limit=4)

    def supported(context: str) -> set[str]:
        body = _topic_evidence_body(context)
        return {
            topic
            for topic in topics
            if _contains_topic_phrase(body, topic)
            and matches_legal_situation(query, context)
        }

    primary_topics = set().union(*(supported(context) for context in primary_contexts))
    retained = [
        context
        for context in corpus_contexts
        if not (supported(context) and supported(context) <= primary_topics)
    ]
    distinct_topic_contexts = list(topic_supporting_contexts(query, retained))
    distinct_topics = set().union(
        *(supported(context) - primary_topics for context in distinct_topic_contexts)
    )
    selected_primary = list(primary_contexts[: max(0, max_evidence)])
    if distinct_topics and max_evidence > 1:
        distinct_slots = min(len(distinct_topic_contexts), max_evidence - 1)
        selected_primary = selected_primary[: max_evidence - distinct_slots]
        distinct_topic_contexts = distinct_topic_contexts[:distinct_slots]
    # Keep verified primary clauses first, but reserve capacity for recognized
    # topics that the primary source does not cover.
    return [*selected_primary, *distinct_topic_contexts]
