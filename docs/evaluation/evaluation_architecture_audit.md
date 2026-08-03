# Evaluation Architecture Audit — VietLex Legal RAG

**Date**: 2026-08-03  
**Repository**: `TanNguyen234/VietLex-Tech-Spec` (`d:\Download\ProfessionalLegalRAG`)  
**Author**: AI Antigravity Pair Programmer  

---

## 1. Overview & Evaluation Flow

The existing evaluation system (`run_eval_suite.py`) measures system accuracy and latency against the 420-row golden dataset (`app/data/namsyntax_legal_qa_420.json`).

### Current Step-by-Step Execution Sequence per Case
1. **Pre-flight & Configuration**:
   - `verify_evaluation_fts`: Checks if SQLite FTS index is built and ready.
   - `warm_evaluation_guardrails`: Initializes NeMo guardrails.
   - `load_evaluation_dataset`: Loads and samples golden cases (default: 12 factoid, 12 multi-hop, 6 unanswerable = 30 cases).
   - Computes `evaluation_fingerprint` (SHA-256 digest of config and query set).
   - Restores existing cached results from `docs/eval_checkpoints.json`.
   - Initializes Ragas judge chain (`Gemini` -> `NVIDIA NIM` -> `Groq` -> `OpenRouter` -> `OmniGate`).
2. **Online Query Execution** (inside pipeline semaphore):
   - **Semantic Cache Check**: Skipped by default unless `--use-cache` is specified.
   - **Input Guardrail**: Calls `check_input_guardrails(query)` (NeMo Guardrails / LLM).
   - **Query Rewriting**: In `run_advanced_rag`, if query > 10 words, calls `rewrite_query(query)` using `generate_llm_response` (OmniGate / remote LLM).
   - **Hybrid Search**: Concurrent execution of:
     - Dense query embedding via Qdrant Cloud API (`embed_query`).
     - Hybrid sparse/dense vector query via Pinecone Cloud API (`query`).
     - Title/Document-number FTS search via local SQLite index (`_fts_index.search`).
   - **Document Resolution & Chunking**: Resolves top document IDs via `balanced_document_ids`, loads full document content from local `ContentStore`, chunks documents via `chunk_document`, scores chunks using local `_lexical_score`, and selects top per-document chunks.
   - **Rerank Candidate Bounding**: Selects top candidate chunks up to `RERANK_CANDIDATE_LIMIT` (12 chunks) via `select_rerank_candidates`.
   - **Remote Reranking**: Calls `get_remote_reranker().rerank` (Qdrant ColBERT `answerai-colbert-small-v1` with fallback to Pinecone `bge-reranker-v2-m3`).
   - **Final Context Selection**: Filters top reranked chunks up to `RERANK_TOP_K` (3 chunks) within `LLM_CONTEXT_MAX_TOKENS` (720 tokens).
   - **Grounded Answer Generation**: Calls `generate_llm_response` with system and user prompts containing retrieved evidence chunks.
   - **Output Guardrail**: Calls `check_output_guardrails` (NeMo Guardrails / LLM).
3. **Ragas Judging** (STILL inside pipeline semaphore):
   - Executes 4 Ragas metric calls concurrently (`faithfulness`, `answer_accuracy`, `context_precision`, `context_recall`) via AsyncOpenAI API calls.
4. **Persistence & Reporting**:
   - Appends/updates query result in `docs/eval_checkpoints.json` via atomic temp file replace.
   - Generates summary report to `docs/system_evaluation_report.md`.

---

## 2. Semaphore Scoping & Concurrency Flaws

### Pipeline Semaphore Location
- **Code Reference**: `run_eval_suite.py` line 1162:
  ```python
  semaphore = asyncio.Semaphore(args.concurrency)
  async def evaluate_case(case: dict) -> dict:
      async with semaphore:
          return await evaluate_single_query(...)
  ```
- **Flaw**: The `semaphore` (default `concurrency=2`) is acquired before `evaluate_single_query` starts and **held throughout the entire duration of the query**, including input guardrails, query rewriting, hybrid retrieval, reranking, generation, output guardrails, AND offline Ragas evaluation!
- **Impact**: When Ragas judge calls experience rate limits (HTTP 429), timeouts, or provider retries, the pipeline semaphore remains locked. No other test cases can proceed with online retrieval or generation, contaminating online end-to-end latency and artificially capping evaluation throughput.

---

## 3. External API Calls per Evaluation Case

For a single evaluation case with query rewriting and Ragas enabled:
1. **Input Guardrail**: 1 LLM call (if enabled).
2. **Query Rewrite**: 1 LLM call (`generate_llm_response`).
3. **Dense Query Embedding**: 1 API call to Qdrant Cloud.
4. **Hybrid Query**: 1 API call to Pinecone Cloud.
5. **Reranking**: 1 API call to Qdrant ColBERT (or Pinecone reranker fallback).
6. **Answer Generation**: 1 LLM call to OmniGate / LLM Provider.
7. **Output Guardrail**: 1 LLM call (if enabled).
8. **Ragas Faithfulness**: 1 LLM judge call.
9. **Ragas Answer Accuracy**: 1 LLM judge call.
10. **Ragas Context Precision**: 1 LLM judge call.
11. **Ragas Context Recall**: 1 LLM judge call.

**Total**: Up to **11 external API calls per query**. With 30 test cases, a single evaluation run makes over 300 remote HTTP requests, creating a massive failure surface for rate-limits and network latency.

---

## 4. LLM Judge Calls & Ragas Reliability Problems

- **Judge Calls per Answer**: 4 distinct LLM API calls per generated answer.
- **Quota & Transient Errors**: If a judge call encounters HTTP 429 or timeout, `run_with_provider_fallback` retries the metric against alternative providers (Gemini -> NVIDIA -> Groq -> OpenRouter -> OmniGate). If retries fail, `eval_status` becomes `"Eval Failed"`, and all Ragas metric values become `None`.
- **Ragas Overhead**: Ragas judge calls account for >70% of total run latency and API cost.
- **Default Behavior Violation**: Ragas runs by default in `run_eval_suite.py` unless `--skip-ragas` is explicitly passed.

---

## 5. Refusal Classification Vulnerabilities

- **Current Implementation** (`run_eval_suite.py` lines 238-252):
  ```python
  REFUSAL_KEYWORDS = [
      "không biết", "không có thông tin", "chưa có dữ liệu",
      "không tìm thấy", "không đủ dữ liệu", "tài liệu không đề cập",
      "xin lỗi", "không thể cung cấp"
  ]
  def is_honest_refusal(text: str) -> bool:
      text_lower = text.lower()
      return any(keyword in text_lower for keyword in REFUSAL_KEYWORDS)
  ```
- **Flaw**: Simple substring keyword matching.
- **Failures**:
  - **False Positive Refusal**: A grounded answer that provides full legal citations and analysis, but includes a disclaimer like *"Nếu trong tài liệu không đề cập thêm về thời hạn..."*, is incorrectly classified as `is_refusal = True`.
  - **False Negative Refusal**: A refusal that uses alternative wording (e.g., *"Cơ sở dữ liệu không chứa quy định về vấn đề này"*) is missed.
  - **Technical Error Confusion**: Network errors or guardrail blocks returning status messages can be misclassified as honest refusals.

---

## 6. Retrieval Metric Calculation Flaws

- **Current Implementation** (`run_eval_suite.py` lines 263-304):
  ```python
  overlap = len(reference_terms & terms) / len(reference_terms)
  if (normalized_reference in normalized) or overlap >= 0.6:
      matched_rank = rank
  ```
- **Flaw**: Direct character substring matching or 60% unigram token overlap between retrieved context strings and `ground_truth_context` text.
- **Impact**:
  - Does NOT verify legal reference identity (`document_id`, `document_number`, `article`, `clause`).
  - A retrieved chunk from Law A Article 5 that shares common legal vocabulary (60% overlap) with Law B Article 10 is wrongly marked as a "gold context hit".
  - Multi-hop requirements are not evaluated (partial vs full evidence coverage).
  - No stage-by-stage candidate survival tracking (Pinecone -> FTS -> Merge -> ContentStore Chunk -> Reranker Input -> Reranker Output -> Final Evidence).

---

## 7. Artifact Overwrite Risks & Reproducibility Gaps

### Overwrite Risks
- Default checkpoint file: `docs/eval_checkpoints.json`
- Default report file: `docs/system_evaluation_report.md`
- Running `python run_eval_suite.py` silently overwrites these files regardless of code changes or model parameters.
- User-owned artifacts (`docs/system_evaluation_report.md`, `docs/eval_checkpoints.json`, `docs/smoke_evaluation_report.md`, `docs/smoke_eval_checkpoints.json`) are vulnerable to accidental clobbering.

### Reproducibility Gaps
- No Git commit SHA, dataset SHA-256 hash, or execution command recorded in generated reports.
- Non-unique execution artifacts (no unique immutable run directory like `docs/evaluation/runs/<run-id>/`).
- Lack of detailed deterministic retrieval metrics (Recall@K, MRR, nDCG, stage survival rates).

---

## 8. Missing Fields in Golden Dataset

The golden dataset `app/data/namsyntax_legal_qa_420.json` contains:
- `question` (string)
- `ground_truth_context` (list of strings)
- `ground_truth_answer` (string)
- `question_type` (`factoid` | `multi-hop` | `unanswerable`)

**Missing Structured Fields**:
- `case_id`
- `answerable` (boolean flag)
- `gold_evidence`: structured list with `document_id`, `document_number`, `article`, `clause`, `required`
- `expected_numbers`, `expected_dates`, `expected_entities`

*Migration Policy*: Preserve original data. Mark missing structured fields as `missing_gold_label` and explicitly report metric coverage denominators.

---

## 9. Planned Code Changes & Target Files

To replace the Ragas-dependent workflow with a trustworthy, immutable, deterministic evaluation architecture:

1. **`app/evaluation/` Package (NEW)**:
   - `app/evaluation/__init__.py`: Package exports.
   - `app/evaluation/schemas.py`: Pydantic models for GoldenCase, GoldEvidence, RetrievalStageTrace, EvaluationRunManifest, EvaluationResult.
   - `app/evaluation/retrieval_metrics.py`: Deterministic Recall@K (Doc/Article/Clause), MRR, nDCG@K, Stage Survival Rates, Legal Citation Hit, Multi-hop Coverage, Technical Error Rates.
   - `app/evaluation/answer_metrics.py`: Normalized EM, Token P/R/F1, Char F1, ROUGE-L, CHRF, Refusal Classifier (distinguishing pure refusal, disclaimer, error, answer), Entity/Number/Date P/R, Citation P/R.
   - `app/evaluation/latency_metrics.py`: Stage-level latency statistics (P50, P95, mean, min, max).
   - `app/evaluation/run_manifest.py`: Git SHA, dataset SHA-256, config fingerprint, run ID generation, atomic file persistence.
   - `app/evaluation/reporting.py`: Markdown report generator for immutable run directories.
2. **Entry Point Scripts (NEW)**:
   - `run_retrieval_eval.py`: Standalone CLI for retrieval evaluation with `--mode retrieval-only`, `--rewrite`, `--guardrails`, `--reranker`, `--concurrency`, `--limit`. Default judge=none.
   - `run_answer_eval.py`: Standalone CLI for full pipeline answer evaluation with optional Ragas audit (`--judge none|ragas`).
3. **Tests (NEW)**:
   - `tests/test_evaluation_framework.py`: Comprehensive test suite for retrieval metrics, answer metrics, refusal classification, schema validation, atomic writes, immutable run directories, and judge-free defaults.
