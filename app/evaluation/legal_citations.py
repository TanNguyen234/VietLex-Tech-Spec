from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


DOC_PATTERN = re.compile(
    r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b",
    re.IGNORECASE,
)
ARTICLE_PATTERN = re.compile(
    r"\bĐiều\s+\d+[A-Za-z]?\b",
    re.IGNORECASE,
)
CLAUSE_PATTERN = re.compile(r"\bKhoản\s+\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class LegalCitation:
    document_number: str = ""
    article: str = ""
    clause: str = ""


def _canonical_locator(value: str, prefix: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    return f"{prefix} {normalized.split(maxsplit=1)[1]}"


def _nearest_index(
    items: list[tuple[int, str]],
    position: int,
) -> int | None:
    if not items:
        return None
    return min(
        range(len(items)),
        key=lambda index: (
            abs(items[index][0] - position),
            0 if items[index][0] <= position else 1,
            items[index][0],
        ),
    )


def parse_legal_citations(text: str) -> list[LegalCitation]:
    documents = [
        (match.start(), match.group().upper())
        for match in DOC_PATTERN.finditer(text)
    ]
    articles = [
        (match.start(), _canonical_locator(match.group(), "Điều"))
        for match in ARTICLE_PATTERN.finditer(text)
    ]
    clauses = [
        (match.start(), _canonical_locator(match.group(), "Khoản"))
        for match in CLAUSE_PATTERN.finditer(text)
    ]
    positioned: list[tuple[int, LegalCitation]] = []
    used_documents: set[int] = set()

    if articles:
        clauses_by_article: dict[int, list[tuple[int, str]]] = {
            index: [] for index in range(len(articles))
        }
        for clause_position, clause in clauses:
            article_index = _nearest_index(articles, clause_position)
            assert article_index is not None
            clauses_by_article[article_index].append(
                (clause_position, clause)
            )

        for article_index, (
            article_position,
            article,
        ) in enumerate(articles):
            document_index = _nearest_index(documents, article_position)
            if document_index is None:
                document_position, document = article_position, ""
            else:
                document_position, document = documents[document_index]
                used_documents.add(document_index)
            linked_clauses = clauses_by_article[article_index]
            if linked_clauses:
                for clause_position, clause in linked_clauses:
                    positioned.append(
                        (
                            min(
                                article_position,
                                clause_position,
                                document_position,
                            ),
                            LegalCitation(document, article, clause),
                        )
                    )
            else:
                positioned.append(
                    (
                        min(article_position, document_position),
                        LegalCitation(document, article, ""),
                    )
                )
    else:
        for clause_position, clause in clauses:
            document_index = _nearest_index(documents, clause_position)
            if document_index is None:
                document_position, document = clause_position, ""
            else:
                document_position, document = documents[document_index]
                used_documents.add(document_index)
            positioned.append(
                (
                    min(clause_position, document_position),
                    LegalCitation(document, "", clause),
                )
            )

    for document_index, (
        document_position,
        document,
    ) in enumerate(documents):
        if document_index not in used_documents:
            positioned.append(
                (
                    document_position,
                    LegalCitation(document_number=document),
                )
            )

    positioned.sort(key=lambda item: item[0])
    deduplicated: list[LegalCitation] = []
    seen: set[LegalCitation] = set()
    for _, unit in positioned:
        if unit not in seen:
            seen.add(unit)
            deduplicated.append(unit)
    return deduplicated
