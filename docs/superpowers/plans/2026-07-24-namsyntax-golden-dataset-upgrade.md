# NamSyntax Golden Dataset Integration & 420-Query Retrieval Evaluation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace legacy evaluation dataset with `NamSyntax/Vietnamese-Legal-QA-RAG` (420 queries), clean up old dataset references, update `run_eval_suite.py` (30 balanced samples) and `scripts/eval_random_samples.py` (2 samples), and create `scripts/export_retrieval_eval_420.py` to generate a structured 420-object evaluation JSON file.

**Architecture:** 
1. **Golden Dataset Onboarding (`app/data/namsyntax_legal_qa_420.json`)**: Downloaded and saved 420 Q&A pairs from HuggingFace `NamSyntax/Vietnamese-Legal-QA-RAG`.
2. **Old Dataset Cleanup**: Remove `docs/evaluation_50_dataset.json` and `app/data/evaluation_50_dataset.json`.
3. **Updated Eval Suite (`run_eval_suite.py` & `scripts/eval_random_samples.py`)**: Updated to consume `namsyntax_legal_qa_420.json` with 30 balanced queries (12 factoid, 12 multi-hop, 6 unanswerable traps) for full suite, and 2 random samples for mini eval.
4. **420-Query Retrieval Exporter (`scripts/export_retrieval_eval_420.py`)**: Generates `docs/retrieval_eval_420_results.json` containing 420 objects formatted with golden fields + `retrieved_contexts` + 4 evaluation metric variables (`is_ground_truth_retrieved`, `is_context_sufficient`, `ground_truth_rank`, `context_coverage_pct`), initialized to `None` / `null` until executed upon user command.

**Tech Stack:** Python 3.10+, HuggingFace Datasets, Qdrant Cloud (AsyncQdrantClient), BGE-M3 Dense + Sparse + BGE-Reranker-v2-M3.

## Global Constraints
- Golden dataset MUST be stored at `app/data/namsyntax_legal_qa_420.json`.
- Output JSON file MUST contain exactly 420 objects.
- Each object MUST include:
  - `question` (str)
  - `ground_truth_context` (list[str])
  - `ground_truth_answer` (str)
  - `question_type` (str: `factoid`, `multi-hop`, `unanswerable`)
  - `retrieved_contexts` (list[str])
  - `is_ground_truth_retrieved` (Optional[bool])
  - `is_context_sufficient` (Optional[bool])
  - `ground_truth_rank` (Optional[int]: 1-3 or 0)
  - `context_coverage_pct` (Optional[int]: 0-100)
- NO Qdrant retrieval or LLM-as-judge evaluation will be executed until user explicitly issues the command ("làm").

---

### Task 1: Clean up Old Evaluation Datasets

**Files:**
- Delete: `docs/evaluation_50_dataset.json`
- Delete: `app/data/evaluation_50_dataset.json`

- [ ] **Step 1: Delete old 50-query dataset files**

```bash
powershell -Command "if (Test-Path docs/evaluation_50_dataset.json) { Remove-Item docs/evaluation_50_dataset.json }; if (Test-Path app/data/evaluation_50_dataset.json) { Remove-Item app/data/evaluation_50_dataset.json }"
```

- [ ] **Step 2: Commit cleanup**

```bash
git rm docs/evaluation_50_dataset.json app/data/evaluation_50_dataset.json
git commit -m "refactor: remove legacy 50-query evaluation dataset"
```

---

### Task 2: Update `run_eval_suite.py` for NamSyntax 30-Query Balanced Evaluation

**Files:**
- Modify: `run_eval_suite.py`
- Test: `pytest tests/test_parser.py`

**Interfaces:**
- Consumes: `app/data/namsyntax_legal_qa_420.json`
- Produces: 30 balanced query evaluation report in `docs/system_evaluation_report.md`

- [ ] **Step 1: Update dataset loader in `run_eval_suite.py`**

In `run_eval_suite.py`:
```python
def load_evaluation_dataset() -> list:
    path = os.path.abspath("app/data/namsyntax_legal_qa_420.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Could not find dataset at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    factoids = [c for c in data if c.get("question_type") == "factoid"][:12]
    multihops = [c for c in data if c.get("question_type") == "multi-hop"][:12]
    unanswerables = [c for c in data if c.get("question_type") == "unanswerable"][:6]
    
    selected = factoids + multihops + unanswerables
    for item in selected:
        item["group"] = item.get("question_type", "Factoid").capitalize()
        item["expected"] = "pass_guardrails" if item.get("question_type") != "unanswerable" else "honest_refusal"
        item["ground_truth"] = item.get("ground_truth_answer", "")
    return selected
```

- [ ] **Step 2: Verify dataset loader execution**

Run: `python -c "from run_eval_suite import load_evaluation_dataset; ds = load_evaluation_dataset(); print('Loaded 30 sample dataset items:', len(ds))"`
Expected: `Loaded 30 sample dataset items: 30`

- [ ] **Step 3: Commit `run_eval_suite.py`**

```bash
git add run_eval_suite.py
git commit -m "feat: update run_eval_suite.py to use 30 balanced queries from NamSyntax dataset"
```

---

### Task 3: Update `scripts/eval_random_samples.py` for NamSyntax 2-Sample Evaluation

**Files:**
- Modify: `scripts/eval_random_samples.py`

**Interfaces:**
- Consumes: `app/data/namsyntax_legal_qa_420.json`
- Produces: Mini evaluation report in `docs/random_eval_sample_report.md`

- [ ] **Step 1: Update dataset loader in `scripts/eval_random_samples.py`**

In `scripts/eval_random_samples.py`:
```python
def load_dataset() -> list:
    path = os.path.abspath("app/data/namsyntax_legal_qa_420.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Could not find dataset at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        item["group"] = item.get("question_type", "Factoid").capitalize()
        item["expected"] = "pass_guardrails"
        item["ground_truth"] = item.get("ground_truth_answer", "")
    return data
```

- [ ] **Step 2: Commit `scripts/eval_random_samples.py`**

```bash
git add scripts/eval_random_samples.py
git commit -m "feat: update eval_random_samples.py for NamSyntax dataset"
```

---

### Task 4: Create 420-Query Retrieval Exporter Script & Pre-formatted JSON Artifact

**Files:**
- Create: `scripts/export_retrieval_eval_420.py`
- Create: `docs/retrieval_eval_420_results.json`

**Interfaces:**
- Consumes: `app/data/namsyntax_legal_qa_420.json`
- Produces: Structured JSON file `docs/retrieval_eval_420_results.json` with 420 pre-formatted objects containing initial `None` metric values.

- [ ] **Step 1: Write `scripts/export_retrieval_eval_420.py`**

Create `scripts/export_retrieval_eval_420.py`:
```python
import os
import sys
import json
import asyncio
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.services.rag_pipeline import run_advanced_rag

def init_420_template_file(source_path: str, output_path: str):
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source file not found: {source_path}")
        
    with open(source_path, "r", encoding="utf-8") as f:
        items = json.load(f)
        
    formatted_objects = []
    for idx, item in enumerate(items, 1):
        formatted_objects.append({
            "id": idx,
            "question": item.get("question", ""),
            "ground_truth_context": item.get("ground_truth_context", []),
            "ground_truth_answer": item.get("ground_truth_answer", ""),
            "question_type": item.get("question_type", ""),
            "retrieved_contexts": [],
            "is_ground_truth_retrieved": None,
            "is_context_sufficient": None,
            "ground_truth_rank": None,
            "context_coverage_pct": None,
            "latency_info": None
        })
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(formatted_objects, f, ensure_ascii=False, indent=2)
    print(f"Initialized 420-query template JSON at: {output_path}")
    return formatted_objects

async def execute_retrieval_420(template_path: str, output_path: str):
    with open(template_path, "r", encoding="utf-8") as f:
        records = json.load(f)
        
    print(f"==================================================")
    print(f"STARTING EXPORT RETRIEVAL EVALUATION FOR 420 QUERIES")
    print(f"==================================================")
    
    for idx, rec in enumerate(records, 1):
        query = rec["question"]
        print(f"[{idx}/420] Querying Qdrant: '{query[:40]}...'")
        
        bot_response, contexts, lat_info = await run_advanced_rag(query)
        rec["retrieved_contexts"] = contexts
        rec["latency_info"] = lat_info
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f" Saved [{idx}/420]")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NamSyntax 420-Query Retrieval Exporter")
    parser.add_argument("--run", action="store_true", help="Execute Qdrant retrieval for 420 queries (Only when requested)")
    args = parser.parse_args()
    
    src = os.path.abspath("app/data/namsyntax_legal_qa_420.json")
    out = os.path.abspath("docs/retrieval_eval_420_results.json")
    
    if not args.run:
        init_420_template_file(src, out)
        print("Template initialized. Pass --run to execute retrieval after Qdrant re-index completes.")
    else:
        asyncio.run(execute_retrieval_420(out, out))
```

- [ ] **Step 2: Run template initialization**

Run: `python scripts/export_retrieval_eval_420.py`
Expected: `Initialized 420-query template JSON at: d:\Download\ProfessionalLegalRAG\docs\retrieval_eval_420_results.json`

- [ ] **Step 3: Commit `scripts/export_retrieval_eval_420.py` and initial JSON**

```bash
git add scripts/export_retrieval_eval_420.py docs/retrieval_eval_420_results.json
git commit -m "feat: add 420-query retrieval exporter script and pre-formatted json template"
```
