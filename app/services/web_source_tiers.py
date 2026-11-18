"""Two-tier web source classification for Vietnamese legal provenance."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

WebSourceTier = Literal["official_primary", "legal_discovery_pivot", "untrusted"]

G7_STREAM_HOST = "g7.cdnchinhphu.vn"
G7_STREAM_PATH = "/api/download/stream"
_G7_STREAM_TOKEN = re.compile(r"[A-Za-z0-9_-]+~{0,2}")
_G7_STREAM_FILENAME = re.compile(r"[\w .()+-]{1,251}\.pdf", re.IGNORECASE)

TIER1_OFFICIAL_DOMAINS: tuple[str, ...] = (
    "vanban.chinhphu.vn",
    "congbao.chinhphu.vn",
    "datafiles.chinhphu.vn",
    "congbaocdn.chinhphu.vn",
    "chinhphu.vn",
    "vbpl.vn",
    "vbpl.moj.gov.vn",
    "phapdien.moj.gov.vn",
    "moj.gov.vn",
    "quochoi.vn",
    "tandtc.gov.vn",
    "gov.vn",
)

TIER2_DISCOVERY_DOMAINS: tuple[str, ...] = (
    "thuvienphapluat.vn",
    "luatvietnam.vn",
)

TAVILY_HYBRID_DOMAINS: tuple[str, ...] = (
    *TIER1_OFFICIAL_DOMAINS,
    *TIER2_DISCOVERY_DOMAINS,
)

# News-only or draft-consultation portals excluded from primary enacted law evidence.
_EXCLUDED_TIER1_HOSTS = frozenset(
    {
        "baochinhphu.vn",
        "xaydungchinhsach.chinhphu.vn",
        "duthao.quochoi.vn",
        "duthaoonline.quochoi.vn",
        "vibonline.com.vn",
    }
)
_DRAFT_HOST_LABEL_RE = re.compile(
    r"^(?:duthao|duthaoonline|du-thao|xaydungchinhsach|layykien|lay-y-kien)$",
    re.IGNORECASE,
)
_DRAFT_PATH_RE = re.compile(
    r"(?:^|/)(?:duthao|du-thao|lay-y-kien|layykien)(?:/|$|-)",
    re.IGNORECASE,
)


def _matches_domain_root(host: str, roots: tuple[str, ...] | frozenset[str]) -> bool:
    return any(host == root or host.endswith(f".{root}") for root in roots)


def is_valid_g7_stream_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        len(url) > 2000
        or any(ord(c) < 33 for c in url)
        or parsed.scheme != "https"
        or parsed.hostname != G7_STREAM_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
        or parsed.path != G7_STREAM_PATH
    ):
        return False
    try:
        parameters = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=2,
        )
    except ValueError:
        return False
    values = dict(parameters)
    return bool(
        len(parameters) == 2
        and set(values) == {"Url", "file_name"}
        and _G7_STREAM_TOKEN.fullmatch(values.get("Url", ""))
        and _G7_STREAM_FILENAME.fullmatch(values.get("file_name", ""))
    )


def classify_web_source_tier(
    url: str,
    domain: str | None = None,
) -> WebSourceTier:
    """Classify a candidate URL into Tier-1 official, Tier-2 discovery pivot, or untrusted."""
    raw = str(url or "")
    if not raw or len(raw) > 2000 or any(ord(c) < 33 for c in raw):
        return "untrusted"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "untrusted"
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        return "untrusted"

    host = parsed.hostname.rstrip(".").casefold()
    declared = str(domain or "").strip().rstrip(".").casefold()

    if host == G7_STREAM_HOST:
        if declared and declared != G7_STREAM_HOST:
            return "untrusted"
        return "official_primary" if is_valid_g7_stream_url(raw) else "untrusted"

    if _matches_domain_root(host, _EXCLUDED_TIER1_HOSTS):
        return "untrusted"
    if host == "gov.vn" or declared == "gov.vn":
        return "untrusted"
    if any(_DRAFT_HOST_LABEL_RE.fullmatch(lbl) for lbl in host.split(".")):
        return "untrusted"
    if declared and any(_DRAFT_HOST_LABEL_RE.fullmatch(lbl) for lbl in declared.split(".")):
        return "untrusted"
    if _DRAFT_PATH_RE.search(parsed.path or ""):
        return "untrusted"

    if _matches_domain_root(host, TIER1_OFFICIAL_DOMAINS):
        if declared and (
            _matches_domain_root(declared, _EXCLUDED_TIER1_HOSTS)
            or not _matches_domain_root(declared, TIER1_OFFICIAL_DOMAINS)
        ):
            return "untrusted"
        return "official_primary"

    if _matches_domain_root(host, TIER2_DISCOVERY_DOMAINS):
        if declared and not _matches_domain_root(declared, TIER2_DISCOVERY_DOMAINS):
            return "untrusted"
        return "legal_discovery_pivot"

    return "untrusted"
