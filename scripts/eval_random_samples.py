import sys
import os
import time
import asyncio
import json
import random
from datetime import datetime

# UTF-8 stdout configuration for Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Shims for Ragas imports
import types
try:
    import langchain_google_vertexai
    if "langchain_community.chat_models" not in sys.modules:
        sys.modules["langchain_community.chat_models"] = types.ModuleType("langchain_community.chat_models")
    v_mod = types.ModuleType("langchain_community.chat_models.vertexai")
    v_mod.ChatVertexAI = getattr(langchain_google_vertexai, "ChatVertexAI", None)
    sys.modules["langchain_community.chat_models.vertexai"] = v_mod
except Exception:
    pass

import httpx
from app.config import get_settings
from app.services.rag_pipeline import run_advanced_rag
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import _faithfulness, _answer_relevancy, _context_precision, _context_recall
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings

class CloudRunEmbeddings(Embeddings):
    def __init__(self):
        settings = get_settings()
        self.api_url = settings.EMBEDDING_API_URL
        self.api_key = settings.EMBEDDING_SERVICE_API_KEY
        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import requests
        resp = requests.post(self.api_url, json={"inputs": texts, "normalize": True}, headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json().get("embeddings", [])

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

def load_dataset() -> list:
    dataset_path = os.path.abspath("app/data/namsyntax_legal_qa_420.json")
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Could not find dataset at: {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        q_type = item.get("question_type", "factoid")
        item["group"] = q_type.capitalize()
        item["expected"] = "pass_guardrails" if q_type != "unanswerable" else "honest_refusal"
        item["ground_truth"] = item.get("ground_truth_answer", "")
    return data


async def run_random_sample_eval(num_samples: int = 2, seed: int = None):
    settings = get_settings()
    valid_cases = load_dataset()
    
    if seed is not None:
        random.seed(seed)
        
    selected_cases = random.sample(valid_cases, min(num_samples, len(valid_cases)))
    print(f"==================================================")
    print(f"RANDOM RAG EVALUATION SAMPLE SUITE ({len(selected_cases)} QUERIES)")
    print(f"Selected from {len(valid_cases)} valid legal RAG test cases with ground_truth")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==================================================")
    
    # Configure LLM for Ragas
    if settings.OPENROUTER_API_KEY:
        print("Using OpenRouter (llama-3.3-70b) for Ragas...")
        llm = ChatOpenAI(
            model="meta-llama/llama-3.3-70b-instruct",
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            request_timeout=30.0,
            max_retries=3
        )
    elif settings.GEMINI_API_KEY:
        print("Using Gemini API for Ragas...")
        llm = ChatOpenAI(
            model="gemini-1.5-flash",
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            request_timeout=30.0,
            max_retries=3
        )
    elif settings.GROQ_API_KEY:
        print("Using Groq (llama-3.3-70b) for Ragas...")
        llm = ChatOpenAI(
            model="llama-3.3-70b-versatile",
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            request_timeout=30.0,
            max_retries=3
        )
    else:
        print("Falling back to OmniGate for Ragas...")
        llm = ChatOpenAI(
            model="legal-core-model",
            api_key=settings.LITELLM_MASTER_KEY,
            base_url=settings.OMNIGATE_BASE_URL,
            default_headers={"drop_params": "true"},
            request_timeout=30.0,
            max_retries=2
        )
        
    embeddings = CloudRunEmbeddings()
    results = []

    for idx, case in enumerate(selected_cases, start=1):
        query = case["query"]
        ground_truth = case.get("ground_truth", "")
        source_snippet = case.get("source_snippet", "")
        
        print(f"\n[{idx}/{len(selected_cases)}] Evaluating Query: '{query}'")
        
        bot_response, contexts, lat_info = await run_advanced_rag(query)
        print(f" -> RAG pipeline finished in {lat_info['t_total']}s (Rewrite: {lat_info['t_rewrite']}s, Dense: {lat_info['t_dense']}s, Sparse: {lat_info['t_sparse']}s, RRF: {lat_info['t_rrf']}s, Rerank: {lat_info['t_rerank']}s, LLM: {lat_info['t_llm']}s).")
        print(f" -> Contexts retrieved: {len(contexts)} chunks")

        print(" -> Running Ragas Evaluator (Faithfulness, Relevance, Precision, Recall)...")
        clean_contexts = [c[:1200] for c in contexts]
        eval_data = {
            "question": [query],
            "contexts": [clean_contexts],
            "answer": [bot_response],
            "ground_truth": [ground_truth[:1200]]
        }
        
        dataset = Dataset.from_dict(eval_data)
        try:
            ragas_result = await asyncio.to_thread(
                evaluate,
                dataset=dataset,
                metrics=[_faithfulness, _answer_relevancy, _context_precision, _context_recall],
                llm=llm,
                embeddings=embeddings,
                raise_exceptions=False
            )
            scores = ragas_result._scores_dict
            faithfulness = float(scores["faithfulness"][0]) if "faithfulness" in scores else 0.0
            relevance = float(scores["answer_relevancy"][0]) if "answer_relevancy" in scores else 0.0
            precision = float(scores["context_precision"][0]) if "context_precision" in scores else 0.0
            recall = float(scores["context_recall"][0]) if "context_recall" in scores else 0.0
        except Exception as e:
            print(f" -> Ragas Eval Warning: {e}")
            faithfulness = relevance = precision = recall = 0.0

        print(f"    Faithfulness: {faithfulness:.2f} | Answer Relevance: {relevance:.2f} | Precision (Top 1-3): {precision:.2f} | Recall: {recall:.2f}")

        results.append({
            "id": idx,
            "query": query,
            "ground_truth": ground_truth,
            "source_snippet": source_snippet,
            "bot_response": bot_response,
            "contexts": contexts,
            "lat_info": lat_info,
            "faithfulness": faithfulness,
            "relevance": relevance,
            "precision": precision,
            "recall": recall
        })

    # Generate Markdown Report
    report_path = os.path.abspath("docs/random_eval_sample_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# BÁO CÁO ĐÁNH GIÁ THỰC TẾ TRÍCH XUẤT MẪU NGẦU NHIÊN (BGE-M3 1024-DIM)\n\n")
        f.write(f"**Thời gian thực thi**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n")
        f.write(f"**Số lượng mẫu ngẫu nhiên**: `{len(results)} câu hỏi` (trích xuất từ 35 câu hỏi Legal RAG hợp lệ có `ground_truth` đầy đủ)  \n\n")
        
        f.write("## 1. Bảng Tổng Hợp Chỉ Số RAGAS & Latency Tổng Thể\n\n")
        f.write("| STT | Câu hỏi | Total Latency | Faithfulness | Answer Relevance | Context Precision (Top 1-3) | Context Recall |\n")
        f.write("| :-: | :--- | :-: | :-: | :-: | :-: | :-: |\n")
        
        avg_f = sum(r["faithfulness"] for r in results) / len(results)
        avg_rel = sum(r["relevance"] for r in results) / len(results)
        avg_p = sum(r["precision"] for r in results) / len(results)
        avg_rec = sum(r["recall"] for r in results) / len(results)
        avg_tot_lat = sum(r["lat_info"]["t_total"] for r in results) / len(results)
        
        for r in results:
            q_short = r["query"] if len(r["query"]) < 50 else r["query"][:50] + "..."
            f.write(f"| {r['id']} | {q_short} | `{r['lat_info']['t_total']:.2f}s` | **{r['faithfulness']:.2f}** | **{r['relevance']:.2f}** | **{r['precision']:.2f}** | **{r['recall']:.2f}** |\n")
            
        f.write(f"| **Trung bình** | **TỔNG THỂ MẪU** | **{avg_tot_lat:.2f}s** | **{avg_f:.2f}** | **{avg_rel:.2f}** | **{avg_p:.2f}** | **{avg_rec:.2f}** |\n\n")

        f.write("## 2. Chi Tiết Latency Theo Từng Bước Trong Luồng RAG (Step-by-Step Latency Breakdown)\n\n")
        f.write("| STT | Query Rewrite | Dense Search (1024d) | Sparse Search (BM25) | RRF Fusion | BGE Reranker (Top 3) | LLM Generation | Total Latency |\n")
        f.write("| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |\n")
        for r in results:
            li = r["lat_info"]
            f.write(f"| {r['id']} | `{li['t_rewrite']:.3f}s` | `{li['t_dense']:.3f}s` | `{li['t_sparse']:.3f}s` | `{li['t_rrf']:.4f}s` | `{li['t_rerank']:.3f}s` | `{li['t_llm']:.3f}s` | **`{li['t_total']:.3f}s`** |\n")
        f.write("\n")
        
        f.write("## 3. Chi Tiết Nội Dung Câu Trả Lời & Context Chunks Trích Xuất\n\n")
        for r in results:
            li = r["lat_info"]
            f.write(f"### Câu #{r['id']}: {r['query']}\n")
            f.write(f"- **Tham chiếu nguồn**: `{r['source_snippet']}`  \n")
            f.write(f"- **Ground Truth**: {r['ground_truth']}  \n")
            f.write(f"- **Latency từng bước**: Rewrite: `{li['t_rewrite']}s` | Dense: `{li['t_dense']}s` | Sparse: `{li['t_sparse']}s` | RRF: `{li['t_rrf']}s` | Rerank: `{li['t_rerank']}s` | LLM Gen: `{li['t_llm']}s` | **Total**: `{li['t_total']}s`  \n")
            f.write(f"- **Điểm Ragas**: Faithfulness: `{r['faithfulness']:.2f}` | Relevance: `{r['relevance']:.2f}` | Precision: `{r['precision']:.2f}` | Recall: `{r['recall']:.2f}`  \n\n")
            f.write(f"**Câu trả lời thực tế từ LLM**:\n> {r['bot_response']}\n\n")
            f.write("**Danh sách Top Context Chunks đã trích xuất từ Qdrant (BGE-M3 + Reranker)**:\n")
            for c_idx, ctx in enumerate(r["contexts"], start=1):
                clean_c = ctx.replace("\n", " ")
                f.write(f"{c_idx}. {clean_c[:300]}...\n")
            f.write("\n---\n\n")

    print(f"\n==================================================")
    print(f"REPORT GENERATED SUCCESSFULLY AT: {report_path}")
    print(f"==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VietLex Random Sample Evaluator")
    parser.add_argument("--n", type=int, default=2, help="Number of random samples to evaluate (default: 2)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = parser.parse_args()
    
    asyncio.run(run_random_sample_eval(num_samples=args.n, seed=args.seed))
