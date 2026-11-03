"""Narrow, non-destructive flags for source defects actually observed in the corpus.

Passing this check is not a legal-validity or comprehensive quality certificate.
"""
from __future__ import annotations

import re


_PAYWALL = re.compile(
    r"Bạn\s+phải\s+đăng\s+nhập\s+hoặc\s+đăng\s+ký\s+Thành\s+Viên\s+"
    r"TVPL\s+Pro\s+để\s+sử\s+dụng", re.IGNORECASE,
)
# Exact raw UTF-8 corpus-body hash verified read-only on 2026-10-26:
# doc387595 (38/2019/QH14), 128 paywall messages. This quarantines its
# clean-looking snippets too; it neither rewrites nor migrates stored data.
_CONTAMINATED_SOURCE_HASHES = frozenset({
    'c65bce6a4c27b72396b5c53270f0994e80be69000ae76e7102e746ccfd492b61',
})


def assess_source_quality(text: str, *, source_sha256: str | None = None) -> dict[str, object]:
    issues = ['commercial_boilerplate'] if _PAYWALL.search(text) else []
    if str(source_sha256 or '').casefold() in _CONTAMINATED_SOURCE_HASHES:
        issues.append('known_contaminated_source')
    english = bool(re.search(r'(?m)^THE NATIONAL ASSEMBLY\b|^Article\s+\d+\.', text))
    vietnamese = bool(re.search(r'(?m)^Điều\s+\d+\.', text))
    return {
        'version': 'observed-source-quality-v1',
        'usable_as_evidence': not issues,
        'issues': issues,
        'language_hint': 'vietnamese' if vietnamese else 'english' if english else 'unknown',
        'warnings': ['translation_unverified'] if english and not vietnamese else [],
    }
