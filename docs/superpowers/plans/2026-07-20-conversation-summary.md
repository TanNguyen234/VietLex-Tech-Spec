# Vietlex Legal RAG & LLMGateway Implementation Plan & Progress Summary

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a comprehensive summary of completed tasks, current tasks in progress, overall goals, and future roadmap steps to finalize the Vietlex Legal RAG optimization and push clean updates to GitHub.

**Architecture:** Real-time production guardrails via NeMo Guardrails integrated with Qdrant Hybrid Search (Dense + BM25 Sparse), backed by a local LiteLLM Gateway (`LLMGateway`) on port 4000. All metrics evaluation (Ragas) runs as an asynchronous background task, separating user-facing latency from evaluation latency.

**Tech Stack:** Python, FastAPI, Qdrant Client, Ragas, NeMo Guardrails, LiteLLM, LangChain, Logfire.

## Global Constraints
- Do not expose any raw API keys (`QDRANT_API_KEY`, `COHERE_API_KEY`, `LITELLM_MASTER_KEY`) in the codebase or plan documentation.
- Maintain compatibility with the Windows environment (forward slashes for links).
- Ensure all Qdrant client instances are closed cleanly to avoid resource leaks.

---

### Task 1: Accomplished Work & Results
**Files:**
- Modified: `app/services/guardrails.py`
- Modified: `guardrails_config/prompts.yml`
- Modified: `guardrails_config/config.yml`
- Modified: `guardrails_config/rails.co`
- Modified: `app/services/rag_pipeline.py`
- Modified: `d:\Download\LLMGateway\config.yaml`

**Results & Goals Achieved:**
1. **Production-grade NeMo Guardrails Integration:**
   - *Goal:* Replace mock guardrail checks with real `nemoguardrails` library v0.23.0.
   - *Action:* Integrated the real Guardrails engine, created Vietnamese prompts for input safety, and structured custom fact-checking rails (`self_check_facts`) with a score threshold of `0.5`.
2. **LiteLLM Event Loop Crash Fixed:**
   - *Goal:* Stop LiteLLM proxy from throwing recursion crashes during high concurrent traffic.
   - *Action:* Found that the `langfuse` logging callback was causing recursive `deepcopy` errors on asyncio coroutines. Disabled the callback in `LLMGateway/config.yaml` to guarantee high availability.
3. **Guardrails Prompt Length Limit Resolved:**
   - *Goal:* Prevent NeMo Guardrails from crashing with `Prompt exceeds max length of 16000 characters` when formatting large legal contexts.
   - *Action:* Configured `max_length: 64000` for the `self_check_facts` task in `guardrails_config/prompts.yml`.
4. **Qdrant Async Connection Optimization:**
   - *Goal:* Fix the hanging execution in `dense_search`.
   - *Action:* Refactored `dense_search` to bypass the synchronous Qdrant `cloud_inference` wrapper (which is unsupported and deadlocks inside `AsyncQdrantClient`) and directly fetch embeddings via `get_embedding` before querying.
5. **Resource Leak Prevention:**
   - *Goal:* Avoid running out of file descriptors during multi-query benchmarks.
   - *Action:* Added explicit client-closing calls (`await qdrant_client.close()`) in both `dense_search` and `sparse_search`.

---

### Task 2: Active Tasks & In-Progress Goals
**Files:**
- Test: `run_eval_suite.py`

**Individual Goals:**
- [ ] **Step 1: Execute clean automated evaluation suite run**
  - Run: `$env:PYTHONPATH="."; .venv\Scripts\python.exe -u run_eval_suite.py`
  - Expected: The evaluation suite runs successfully without hangs or crashes, querying the 20 benchmark test cases (safe, off-topic, and legal queries), and computes final scores.
- [ ] **Step 2: Collect Ragas and Guardrails metrics**
  - Expected: Generate `docs/system_evaluation_report.md` showing correct Ragas metrics (Faithfulness, Relevance, Precision, Recall) and real Guardrails accuracy metrics.

---

### Task 3: Future Roadmap & Finalization
**Files:**
- Modify: `README.md`
- Audit: Both repository file trees for security leaks.

**Roadmap Steps:**
- [ ] **Step 1: Refactor README.md to address the 10-point critique**
  - Rework the benchmark presentation: clearly separate user-facing response times from background Ragas evaluation times.
  - Explain the cache hit rate mechanism (0% in benchmark due to unique queries, but active in caching repeated queries).
  - Tone down marketing claims and present the project as a high-fidelity portfolio demonstration.
  - Align build badges with the correct GitHub repository structure.
- [ ] **Step 2: Security & API Key Audit**
  - Run a scan over the local repositories `d:\Download\ProfessionalLegalRAG` and `d:\Download\LLMGateway` to ensure no sensitive credentials (e.g. `QDRANT_API_KEY`, `COHERE_API_KEY`, LiteLLM keys) are hardcoded in the codebase.
- [ ] **Step 3: Commit and Push to GitHub**
  - Perform git commits and push the updated branch to remote for both repositories.
