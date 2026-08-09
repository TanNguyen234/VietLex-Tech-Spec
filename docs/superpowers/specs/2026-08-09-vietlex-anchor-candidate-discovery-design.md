# VietLex Anchor Candidate Discovery Design

**Date:** 2026-08-09
**Scope:** P1 provider-free gold-adjudication candidate discovery

## Problem and evidence

The immutable 40-case queue contains 52 evidence rows and 624 candidates, but none of those candidates satisfies `required_level_supported`. The rows come from the 420-case NamSyntax golden dataset; the candidates are only a bounded title/document-number FTS search over the pinned 518,255-document corpus.

The source dataset omits document identity while stating that `ground_truth_context` contains raw source-document chunks: <https://huggingface.co/datasets/NamSyntax/Vietnamese-Legal-QA-RAG>.

A read-only reality probe established:

- all 52 queued reference anchors occur in corpus documents `72/2020/QH14` or `59/2020/QH14`;
- the existing title-only top-12 search did not surface either source document;
- 32 of 52 rows satisfy the existing document/article/clause gate when those source documents are evaluated;
- the remaining 20 rows expose citation/structure conflicts and must remain pending for human review.

The root cause is candidate discovery, not missing corpus content: a raw legal passage does not reliably contain the source document's title or number, so title-only FTS cannot resolve it.

## Considered approaches

1. **Hardcode the two matching laws.** Fast, but dataset-specific and unauditable. Rejected.
2. **Build or restore a full body FTS index.** General, but it changes the persistent indexing boundary, requires a 518,255-document rebuild, and is outside P1 authority. Rejected.
3. **Read-only tiered anchor scan.** Retain exact number/title FTS, then scan bounded normative legal-type tiers for unresolved raw anchors. Chosen.

## Chosen design

Candidate discovery keeps the current source-sidecar and FTS candidates. For evidence without a resolved document number or document ID, it performs a deterministic read-only anchor scan:

1. Scan primary normative types (`Hiến pháp`, `Luật`, `Pháp lệnh`) in document-ID order.
2. For anchors still unmatched, scan secondary normative types (`Nghị định`, `Nghị quyết`, `Thông tư`, `Thông tư liên tịch`, `Văn bản hợp nhất`, `Quy định`, `Quy chế`).
3. Stop an anchor after the first tier that yields matches; retain up to the existing candidate limit.
4. Rank source-sidecar IDs first, anchor-scan matches second, and title FTS candidates last.
5. Reuse the shared anchor matcher and existing structural chunk gate. Never infer `verified` status.

`ContentStore` exposes a read-only, ordered document-ID iterator filtered by legal type. Candidate discovery normalizes each scanned document once before checking all unresolved anchors. Candidate diagnostics identify the scan tier and explicitly record that the search is not a complete corpus search.

## Boundaries and failure behavior

- No provider calls, ingestion, reindexing, vector changes, corpus writes, evidence decisions, preview, or promotion.
- No claim that absence from the scanned tiers means `corpus_missing`.
- Missing scanned documents, invalid identities, or invalid hashes fail closed.
- The existing immutable queue is never overwritten; successful tooling produces a new queue directory after a clean commit.
- Human review remains mandatory for every promotion decision, especially the 20 citation/structure conflicts.

## Verification

- Regression test: a correct source law absent from title FTS is discovered by exact anchor and ranked ahead of FTS noise.
- Regression test: legal-type iteration is ordered, filtered, bounded, and read-only.
- Existing adjudication tests remain unchanged where stores do not expose tier scanning.
- Focused tests, broader evaluation/ingestion tests, Ruff, compilation, CRG review, and one final full suite run on stable source.
