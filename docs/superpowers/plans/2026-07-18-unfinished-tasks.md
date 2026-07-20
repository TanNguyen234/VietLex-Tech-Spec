# Unfinished Tasks Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume and complete the VLegal document indexing process and run the full automated system evaluation suite to generate the English system evaluation report.

**Architecture:** The indexer checks existing document UUIDs in Qdrant before fetching embeddings, making it safe to resume. The evaluation suite runs 20 Vietnamese legal and safety queries, evaluates performance using 4 Ragas metrics with custom OmniGateEmbeddings, and outputs results in English to `docs/system_evaluation_report.md`.

**Tech Stack:** Python, Qdrant Client, Ragas, Datasets, HTTPX, LangChain.

## Global Constraints
- Run on Windows environment, using forward slashes for links.
- Retries with linear backoffs should be used for LLM and Embedding API calls.
- Do not mock core services (Qdrant, Cohere, OmniGate).

---

### Task 1: Resume VLegal Indexer
**Files:**
- Modify: `app/ingestion/vlegal_indexer.py` (No changes needed, run as is)

- [ ] **Step 1: Check currently indexed points count**
  Run: `.venv\Scripts\python.exe C:\Users\VI" "TINH" "THANH" "AN\.gemini\antigravity-ide\brain\1757c586-868d-4c3c-ad21-982fa6512c15\scratch\count_points.py`
  Expected: Prints current points count (should be >= 850).
- [ ] **Step 2: Resume vlegal indexer execution**
  Run: `.venv\Scripts\python.exe -u -m app.ingestion.vlegal_indexer`
  Expected: The script skips already indexed documents and resumes importing remaining batches of the `datht/vlegal` dataset.
- [ ] **Step 3: Verify points count after completion**
  Run: `.venv\Scripts\python.exe C:\Users\VI" "TINH" "THANH" "AN\.gemini\antigravity-ide\brain\1757c586-868d-4c3c-ad21-982fa6512c15\scratch\count_points.py`
  Expected: Points count has successfully increased and all VLegal data is ingested.

---

### Task 2: Execute Automated Evaluation Suite
**Files:**
- Modify: `run_eval_suite.py` (Verify it is configured with custom `OmniGateEmbeddings`)

- [ ] **Step 1: Run the evaluation suite**
  Run: `.venv\Scripts\python.exe -u run_eval_suite.py`
  Expected: The script runs all 20 test cases, calls the Ragas evaluator using custom embeddings to measure 4 metrics (Faithfulness, Answer Relevance, Context Precision, Context Recall), and writes the final report.
- [ ] **Step 2: Verify generation of docs/system_evaluation_report.md**
  Verify that `docs/system_evaluation_report.md` exists and contains English statistics matching the executed run.
