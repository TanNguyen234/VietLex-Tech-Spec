# VietLex Anchor Candidate Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface deterministic source-document candidates for raw golden anchors that title/document-number FTS cannot resolve, without changing corpus indexes or promoting evidence.

**Architecture:** Add an ordered, read-only legal-type iterator to `ContentStore`. Candidate discovery uses the shared normalized anchor matcher to scan primary and then secondary normative document types once for all unresolved evidence, ranks matches before FTS noise, and leaves every decision pending.

**Tech Stack:** Python 3.12, SQLite read-only URI connections, Zstandard content store, Pydantic models, pytest.

## Global Constraints

- Worktree creation remains OFF.
- No provider calls, ingestion, reindexing, vector changes, corpus writes, evidence decisions, preview, or promotion.
- Do not overwrite the existing immutable queue.
- Absence from scan tiers never implies `corpus_missing`.
- Use TDD RED → minimal GREEN for every behavior change.

---

### Task 1: Filtered read-only content-store iteration

**Files:**
- Modify: `app/ingestion/content_store.py:806`
- Test: `tests/ingestion/test_content_store.py`

**Interfaces:**
- Consumes: existing `ContentStore.path` SQLite database.
- Produces: `ContentStore.iter_document_ids_by_legal_types(legal_types: Sequence[str], *, after_id: int, limit: int) -> list[int]`.

- [ ] **Step 1: Write the failing behavior test**

Add a real temporary content-store test that changes the four fixture metadata rows to literal legal types, then asserts ordered filtering and pagination:

```python
def test_store_iterates_document_ids_by_legal_type_read_only(tmp_path: Path) -> None:
    content_store = _content_store_module()
    snapshot = tmp_path / "snapshot"
    _write_metadata(snapshot, [1, 2, 3, 4])
    _write_content(snapshot, [1, 2, 3, 4], [f"Nội dung {i}" for i in range(1, 5)])
    database = tmp_path / "filtered.sqlite3"
    content_store.build_content_store(snapshot, database, expected_count=4, workers=1)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "UPDATE metadata SET legal_type = ? WHERE document_id = ?",
            [("Luật", 1), ("Nghị định", 2), ("Luật", 3), ("Quyết định", 4)],
        )

    store = content_store.ContentStore(database)
    assert store.iter_document_ids_by_legal_types(
        ["Luật", "Nghị định"], after_id=1, limit=2
    ) == [2, 3]
    assert store.iter_document_ids_by_legal_types(
        ["Luật"], after_id=1, limit=1
    ) == [3]
```

Break caught: filtered iteration is missing, unordered, ignores `after_id`, or writes to the store.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest tests/ingestion/test_content_store.py::test_store_iterates_document_ids_by_legal_type_read_only -q
```

Expected: FAIL with `AttributeError: 'ContentStore' object has no attribute 'iter_document_ids_by_legal_types'`.

- [ ] **Step 3: Add the minimal iterator**

Import `Sequence` from `typing` and add:

```python
def iter_document_ids_by_legal_types(
    self,
    legal_types: Sequence[str],
    *,
    after_id: int,
    limit: int,
) -> list[int]:
    values = sorted({value.strip() for value in legal_types if value.strip()})
    if limit <= 0 or not values:
        return []
    placeholders = ",".join("?" for _ in values)
    with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT document_id FROM metadata WHERE document_id > ? "
            f"AND legal_type IN ({placeholders}) "
            "ORDER BY document_id LIMIT ?",
            (after_id, *values, limit),
        ).fetchall()
    return [int(row[0]) for row in rows]
```

- [ ] **Step 4: Run GREEN and focused ingestion tests**

```powershell
python -m pytest tests/ingestion/test_content_store.py -q
```

Expected: all tests pass.

---

### Task 2: Shared normalized matcher and tiered anchor candidates

**Files:**
- Modify: `audit_golden_dataset.py:90`
- Modify: `app/evaluation/adjudication_candidates.py`
- Test: `tests/evaluation/test_gold_adjudication.py`

**Interfaces:**
- Consumes: Task 1 iterator, `GoldenCase.reference_contexts`, existing `check_anchor_match`, existing structural chunk gates.
- Produces: `check_normalized_anchor_match(normalized_snippet: str, normalized_content: str)` and candidates with `discovery_method="normative_anchor_scan"`.

- [ ] **Step 1: Write matcher and discovery regression tests**

Add a matcher equivalence test using hand-normalized literals:

```python
def test_normalized_anchor_match_preserves_exact_match_contract():
    from audit_golden_dataset import check_normalized_anchor_match

    assert check_normalized_anchor_match(
        "điều 2 nội dung nguồn",
        "mở đầu điều 2 nội dung nguồn kết thúc",
    ) == (True, "full_anchor_exact", {"full_anchor_matched": True})
```

Add `_ScanningFakeContentStore`, which filters its complete fake metadata by requested legal types and records tier calls. Add a discovery test where FTS returns unrelated document `2`, while source law `9` is available only through the legal-type iterator:

```python
def test_candidate_discovery_scans_normative_anchors_before_fts_noise():
    from app.evaluation.adjudication_candidates import discover_adjudication_candidates

    anchor = "Điều 2\n1. Nội dung nguồn pháp luật đủ dài để xác minh chính xác."
    case = GoldenCase(
        case_id="anchor-scan", question="Nội dung được quy định thế nào?",
        question_type="factoid", answerable=True, reference_answer="Trả lời",
        reference_contexts=[anchor],
    )
    evidence = GoldEvidence(
        evidence_item_id="anchor-evidence", case_id=case.case_id,
        article="Điều 2", required=True, required_level="article",
        status=EvidenceStatus.NO_CITATION_EXTRACTED,
    )
    store = _ScanningFakeContentStore({
        2: _stored_document(2, number="2/QĐ", content="Không có anchor."),
        9: _stored_document(9, number="9/2026/QH15", content=anchor, legal_type="Luật"),
    })

    candidates = discover_adjudication_candidates(
        cases_by_id={case.case_id: case}, labels_by_case_id={case.case_id: [evidence]},
        selected_case_ids=[case.case_id], content_store=store,
        fts_index=_FakeFts([2]), candidate_limit=2,
    )[case.case_id]

    assert [item.document_id for item in candidates] == [9, 2]
    assert candidates[0].discovery_method == "normative_anchor_scan"
    assert candidates[0].required_level_supported is True
    assert candidates[0].anchor_diagnostics["anchor_scan_tier"] == "primary_normative"
    assert candidates[0].anchor_diagnostics["corpus_search_complete"] is False
```

Break caught: the correct corpus source remains absent when its title/number is not in the golden row, scan candidates rank after FTS noise, or scan results are mislabeled complete.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/evaluation/test_gold_adjudication.py::test_normalized_anchor_match_preserves_exact_match_contract tests/evaluation/test_gold_adjudication.py::test_candidate_discovery_scans_normative_anchors_before_fts_noise -q
```

Expected: import failure for `check_normalized_anchor_match` and discovery failure `[2] != [9, 2]`.

- [ ] **Step 3: Refactor the shared matcher without changing its contract**

Move the existing normalized logic into:

```python
def check_normalized_anchor_match(
    normalized_snippet: str,
    normalized_content: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    # Existing full-anchor and three-window logic, unchanged.

def check_anchor_match(snippet: str, content: str) -> Tuple[bool, str, Dict[str, Any]]:
    return check_normalized_anchor_match(norm_text(snippet), norm_text(content))
```

- [ ] **Step 4: Implement one global tiered scan**

Add constants:

```python
_ANCHOR_SCAN_BATCH_SIZE = 256
_ANCHOR_SCAN_TIERS = (
    ("primary_normative", ("Hiến pháp", "Luật", "Pháp lệnh")),
    (
        "secondary_normative",
        ("Nghị định", "Nghị quyết", "Thông tư", "Thông tư liên tịch",
         "Văn bản hợp nhất", "Quy định", "Quy chế"),
    ),
)
```

Implement `_discover_anchor_scan_ids(...)` to:

- target only evidence without `document_id` and `document_number`;
- normalize each reference anchor once;
- call `iter_document_ids_by_legal_types` in ordered batches;
- validate every loaded document and normalize each body once;
- call `check_normalized_anchor_match` for each active anchor;
- keep at most `candidate_limit` IDs per evidence;
- stop an evidence after its first matching tier;
- return match IDs plus the tier name; return empty mappings when the store lacks the optional iterator.

In `discover_adjudication_candidates`, compute the scan once before the per-case output loop. For each evidence, use stable order:

```python
document_ids = _stable_bounded_ids(
    source_ids,
    [*anchor_scan_ids.get(evidence.evidence_item_id, ()), *fts_ids],
    candidate_limit,
)
```

Mark scan candidates with `discovery_method="normative_anchor_scan"`. Extend only their matcher diagnostics with:

```python
{
    **diagnostics,
    "anchor_scan_tier": anchor_scan_tiers[evidence.evidence_item_id],
    "corpus_search_complete": False,
}
```

Do not set any decision or evidence status.

- [ ] **Step 5: Run focused GREEN**

```powershell
python -m pytest tests/evaluation/test_gold_adjudication.py tests/ingestion/test_content_store.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Review and stable verification**

```powershell
python -m pytest tests/evaluation/test_gold_adjudication.py tests/evaluation/test_legal_citations.py tests/evaluation/test_provenance.py tests/evaluation/test_preflight.py tests/evaluation/test_runtime_contracts.py tests/evaluation/test_default_entrypoints.py tests/ingestion/test_content_store.py tests/ingestion/test_legal_fts.py tests/ingestion/test_legal_text.py -q
python -m ruff check --select E4,E7,E9,F app audit_golden_dataset.py run_gold_adjudication.py tests/evaluation/test_gold_adjudication.py tests/ingestion/test_content_store.py
python -m compileall -q app tests audit_golden_dataset.py run_gold_adjudication.py
git diff --check
python -m pytest -q
```

Then run CRG changed-code review and resolve every important finding. Expected final full suite baseline: at least `371 passed, 1 skipped` with the new tests added.

- [ ] **Step 7: Commit the review-clean tooling change**

```powershell
git add -- app/ingestion/content_store.py app/evaluation/adjudication_candidates.py audit_golden_dataset.py tests/ingestion/test_content_store.py tests/evaluation/test_gold_adjudication.py docs/superpowers/plans/2026-08-09-vietlex-anchor-candidate-discovery.md
git commit -m "fix(eval): discover gold candidates by corpus anchors"
```

---

### Task 3: Generate and inspect a new immutable real queue

**Files:**
- Create: the unique generated run directory's `queue.json` under `docs/evaluation/adjudication/queues/`
- Create: the same generated run directory's `decision_template.json`
- Create: the same generated run directory's `queue_summary.json`
- Modify: `docs/evaluation/CURRENT_STATUS.md`

**Interfaces:**
- Consumes: clean Task 2 commit, pinned dataset/sidecar/content store/FTS.
- Produces: a new immutable pending human-review queue; never modifies the old queue.

- [ ] **Step 1: Generate the queue from clean source**

```powershell
python -u run_gold_adjudication.py queue --dataset D:\Download\ProfessionalLegalRAG\app\data\namsyntax_legal_qa_420.json --sidecar D:\Download\ProfessionalLegalRAG\docs\evaluation\gold_labels\namsyntax_legal_qa_420_labels_v2.json --content-store D:\Download\ProfessionalLegalRAG\data\huggingface\content_store.sqlite3 --fts D:\Download\ProfessionalLegalRAG\data\huggingface\legal_fts.sqlite3 --output-root D:\Download\ProfessionalLegalRAG\docs\evaluation\adjudication\queues --target-cases 40 --candidate-limit 12
```

Expected: unique queue directory, `provider_calls=0`, 40 selected cases, 52 pending decisions.

- [ ] **Step 2: Validate real candidate outcomes**

Read the new artifacts and assert:

- queue/source hashes and clean Git provenance validate;
- no prior queue was overwritten;
- documents `72/2020/QH14` and `59/2020/QH14` are surfaced by corpus anchors;
- at least the 32 empirically established rows have `required_level_supported=true`;
- all decisions remain `pending` and no preview/promotion exists.

Run:

```powershell
python -m pytest tests/evaluation/test_gold_adjudication.py -q
git diff --check
```

- [ ] **Step 3: Update current status and commit only real artifacts**

Record exact run ID, hashes, counts, command, elapsed time, Git SHA, zero provider calls, and remaining citation conflicts in `docs/evaluation/CURRENT_STATUS.md`. Stage the new run directory and status file explicitly, then:

```powershell
git commit -m "data(eval): publish anchor-backed adjudication queue"
```

Stop at the human decision gate. Do not populate decisions, preview, or promote evidence automatically.
