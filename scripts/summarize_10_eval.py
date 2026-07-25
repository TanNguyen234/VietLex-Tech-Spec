import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

with open("docs/retrieval_eval_420_results.json", "r", encoding="utf-8") as f:
    records = json.load(f)[:10]

print("====================================================================================================")
print("                                BÁO CÁO ĐÁNH GIÁ CHI TIẾT 10 CÂU HỎI ĐẦU TIÊN                        ")
print("====================================================================================================")

for r in records:
    lat = r.get("latency_info") or {}
    print(f"ID: {r['id']} | Loại: {r['question_type'].upper()}")
    print(f"Câu hỏi: {r['question']}")
    print(f"Ground Truth Rank: Top {r['ground_truth_rank']} (Retrieved: {r['is_ground_truth_retrieved']})")
    print(f"Context Coverage: {r['context_coverage_pct']}% | Context Sufficient: {r['is_context_sufficient']}")
    print(f"Độ trễ (Latency): Total {lat.get('t_total', 0)}s | Rewrite: {lat.get('t_rewrite', 0)}s | Dense: {lat.get('t_dense', 0)}s | Sparse: {lat.get('t_sparse', 0)}s | Rerank: {lat.get('t_rerank', 0)}s | LLM: {lat.get('t_llm', 0)}s")
    print("----------------------------------------------------------------------------------------------------")

factoid_count = sum(1 for r in records if r['question_type'] == 'factoid')
multihop_count = sum(1 for r in records if r['question_type'] == 'multi-hop')
trap_count = sum(1 for r in records if r['question_type'] == 'unanswerable')

top1_count = sum(1 for r in records if r['ground_truth_rank'] == 1)
top3_count = sum(1 for r in records if 1 <= r['ground_truth_rank'] <= 3)

avg_total_lat = round(sum(r.get("latency_info", {}).get("t_total", 0) for r in records) / len(records), 2)
avg_rerank_lat = round(sum(r.get("latency_info", {}).get("t_rerank", 0) for r in records) / len(records), 2)

print("\n====================================================================================================")
print("                                    THỐNG KÊ TỔNG HỢP 10 CÂU                                        ")
print("====================================================================================================")
print(f"- Tổng số câu đánh giá: 10 (Factoid: {factoid_count}, Multi-hop: {multihop_count}, Bẫy/Unanswerable: {trap_count})")
print(f"- Tỷ lệ Ground Truth lọt Top 1 (Rank 1): {top1_count}/10 ({top1_count*10}%)")
print(f"- Tỷ lệ Ground Truth lọt Top 1-3 (Hit Rate@3): {top3_count}/10 ({top3_count*10}%)")
print(f"- Thời gian phản hồi trung bình (Avg Total Latency): {avg_total_lat}s")
print(f"- Thời gian Reranking trung bình (Avg BGE-Reranker-v2-M3): {avg_rerank_lat}s")
print("====================================================================================================")
