from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from pyvi import ViTokenizer
from qdrant_client.models import SparseVector


def normalized_terms(text: str) -> list[str]:
    segmented = ViTokenizer.tokenize((text or "").lower())
    return [
        term
        for term in segmented.split()
        if any(character.isalnum() for character in term)
    ]


def stable_term_id(term: str) -> int:
    digest = hashlib.blake2b(
        term.encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF


def _sparse_vector(weights: dict[int, float]) -> SparseVector:
    ordered = sorted(weights.items())
    return SparseVector(
        indices=[item[0] for item in ordered],
        values=[float(item[1]) for item in ordered],
    )


@dataclass(frozen=True)
class SparseEncoder:
    average_document_length: float
    max_terms: int = 2_048
    max_nonzero_terms: int = 192
    protected_leading_terms: int = 64
    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self) -> None:
        if self.max_terms <= 0 or self.max_nonzero_terms <= 0:
            raise ValueError("Sparse term limits must be positive.")
        if self.protected_leading_terms < 0:
            raise ValueError(
                "protected_leading_terms must be non-negative."
            )

    def encode_document(self, text: str) -> SparseVector:
        terms = normalized_terms(text)[: self.max_terms]
        counts = Counter(terms)
        document_length = max(1, len(terms))
        weights: defaultdict[int, float] = defaultdict(float)
        first_term_ids: list[int] = []
        first_positions: dict[int, int] = {}
        for position, term in enumerate(terms):
            term_id = stable_term_id(term)
            if term_id not in first_positions:
                first_positions[term_id] = position
                first_term_ids.append(term_id)
        for term, frequency in counts.items():
            denominator = frequency + self.k1 * (
                1
                - self.b
                + self.b
                * document_length
                / max(1.0, self.average_document_length)
            )
            weight = frequency * (self.k1 + 1) / denominator
            weights[stable_term_id(term)] += float(weight)
        if len(weights) > self.max_nonzero_terms:
            protected_count = min(
                self.protected_leading_terms,
                self.max_nonzero_terms,
            )
            selected = first_term_ids[:protected_count]
            selected_set = set(selected)
            ranked_remaining = sorted(
                (
                    term_id
                    for term_id in weights
                    if term_id not in selected_set
                ),
                key=lambda term_id: (
                    -weights[term_id],
                    first_positions[term_id],
                    term_id,
                ),
            )
            selected.extend(
                ranked_remaining[
                    : self.max_nonzero_terms - len(selected)
                ]
            )
            weights = defaultdict(
                float,
                {
                    term_id: weights[term_id]
                    for term_id in selected
                },
            )
        return _sparse_vector(dict(weights))

    def encode_query(self, text: str) -> SparseVector:
        counts = Counter(normalized_terms(text)[: self.max_terms])
        weights: defaultdict[int, float] = defaultdict(float)
        for term, frequency in counts.items():
            weights[stable_term_id(term)] += 1.0 + math.log(frequency)
        return _sparse_vector(dict(weights))
