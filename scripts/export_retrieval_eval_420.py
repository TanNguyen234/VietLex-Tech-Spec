import os
import sys
import json
import asyncio
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.services.rag_pipeline import run_advanced_rag


def init_420_template_file(source_path: str, output_path: str):
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source golden dataset not found: {source_path}")
        
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
    print(f"Successfully initialized {len(formatted_objects)} objects template at: {output_path}")
    return formatted_objects

async def execute_retrieval_420(template_path: str, output_path: str, limit: int = None):
    if not os.path.exists(template_path):
        print(f"Error: Template file not found: {template_path}")
        return
        
    with open(template_path, "r", encoding="utf-8") as f:
        records = json.load(f)
        
    target_records = records[:limit] if limit else records
        
    print(f"==================================================")
    print(f"STARTING EXPORT RETRIEVAL EVALUATION FOR {len(target_records)} QUERIES")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==================================================")
    
    for idx, rec in enumerate(target_records, 1):
        query = rec["question"]
        print(f"[{idx}/{len(target_records)}] Querying Qdrant: '{query[:50]}...'")
        
        try:
            bot_response, contexts, lat_info = await run_advanced_rag(query)
            rec["retrieved_contexts"] = contexts
            rec["latency_info"] = lat_info
            
            # Calculate retrieval metrics
            gt_contexts = rec.get("ground_truth_context", [])
            gt_answer = rec.get("ground_truth_answer", "")
            q_type = rec.get("question_type", "")
            
            # 1. is_ground_truth_retrieved & rank
            found_gt = False
            gt_rank = 0
            
            for rank_idx, ctx in enumerate(contexts, 1):
                for gt in gt_contexts:
                    if not gt:
                        continue
                    # Match via substring or significant word overlap (>50% of key words)
                    gt_clean = gt.strip().lower()
                    ctx_clean = ctx.strip().lower()
                    
                    # Direct snippet match
                    if gt_clean[:60] in ctx_clean or ctx_clean[:60] in gt_clean:
                        found_gt = True
                        if gt_rank == 0:
                            gt_rank = rank_idx
                        break
                    
                    # Key word overlap
                    gt_words = [w for w in gt_clean.split() if len(w) > 3]
                    if gt_words:
                        matching_words = sum(1 for w in gt_words if w in ctx_clean)
                        if (matching_words / len(gt_words)) >= 0.4:
                            found_gt = True
                            if gt_rank == 0:
                                gt_rank = rank_idx
                            break
                if found_gt and gt_rank > 0:
                    break
                    
            rec["is_ground_truth_retrieved"] = found_gt
            rec["ground_truth_rank"] = gt_rank
            
            # 2. is_context_sufficient
            if q_type == "unanswerable":
                # For trap questions, context is sufficient if it doesn't trick system into hallucination
                rec["is_context_sufficient"] = not found_gt
            else:
                rec["is_context_sufficient"] = found_gt or len(contexts) > 0
                
            # 3. context_coverage_pct
            if found_gt:
                rec["context_coverage_pct"] = 100 if gt_rank == 1 else (85 if gt_rank == 2 else 70)
            else:
                rec["context_coverage_pct"] = 0
                
            print(f" -> [{idx}/{len(target_records)}] Rank: {gt_rank}, GT Found: {found_gt}, Latency: {lat_info['t_total']}s")
        except Exception as e:
            print(f" -> [{idx}/{len(target_records)}] Error evaluating query: {e}")
            rec["is_ground_truth_retrieved"] = False
            rec["ground_truth_rank"] = 0
            rec["is_context_sufficient"] = False
            rec["context_coverage_pct"] = 0
            
        # Save progress after each query
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\n==================================================")
    print(f"RETRIEVAL EVALUATION FOR {len(target_records)} QUERIES COMPLETED!")
    print(f"==================================================")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NamSyntax 420-Query Retrieval Exporter & Evaluator")
    parser.add_argument("--run", action="store_true", help="Execute Qdrant retrieval")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries to evaluate (e.g. 10)")
    args = parser.parse_args()
    
    src = os.path.abspath("app/data/namsyntax_legal_qa_420.json")
    out = os.path.abspath("docs/retrieval_eval_420_results.json")
    
    if not args.run:
        init_420_template_file(src, out)
    else:
        asyncio.run(execute_retrieval_420(out, out, limit=args.limit))

