import os
import sys
import json
import httpx
from datasets import load_dataset

# Set UTF-8 encoding for Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RAW_DATA_DIR = os.path.abspath("app/data/raw_data")
os.makedirs(RAW_DATA_DIR, exist_ok=True)

def download_nam_syntax_dataset():
    print("1. Downloading HuggingFace dataset: 'NamSyntax/Vietnamese-Legal-QA-RAG'...")
    out_file = os.path.join(RAW_DATA_DIR, "vietnamese_legal_qa_rag.json")
    try:
        ds = load_dataset("NamSyntax/Vietnamese-Legal-QA-RAG", split="train")
        rows = [dict(row) for row in ds]
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        print(f"✓ Saved {len(rows)} rows to {out_file}")
    except Exception as e:
        print(f"Error downloading NamSyntax/Vietnamese-Legal-QA-RAG: {e}")

def download_vlegal_raw_dataset():
    print("2. Downloading HuggingFace dataset files: 'datht/vlegal'...")
    out_file = os.path.join(RAW_DATA_DIR, "vlegal_benchmark.json")
    task_files = [
        "data/task_1_1.jsonl", "data/task_1_2.jsonl",
        "data/task_2_1.jsonl", "data/task_2_2.jsonl",
        "data/task_3_1.jsonl", "data/task_3_2.jsonl",
        "data/task_4_1.jsonl", "data/task_4_2.jsonl",
        "data/task_5_1.jsonl", "data/task_5_2.jsonl"
    ]
    
    all_vlegal_data = []
    headers = {"User-Agent": "VietLex-RAG/1.0"}
    
    with httpx.Client(timeout=30.0) as client:
        for tf in task_files:
            url = f"https://huggingface.co/datasets/datht/vlegal/raw/main/{tf}"
            try:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    lines = [l for l in res.text.split("\n") if l.strip()]
                    parsed = []
                    for line in lines:
                        try:
                            parsed.append(json.loads(line))
                        except Exception:
                            pass
                    all_vlegal_data.extend(parsed)
                    print(f"  Downloaded {len(parsed)} items from {tf}")
            except Exception as e:
                print(f"  Warning fetching {tf}: {e}")
                
    if all_vlegal_data:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_vlegal_data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        print(f"✓ Saved {len(all_vlegal_data)} vlegal items to {out_file}")

if __name__ == "__main__":
    print("==================================================")
    print("STARTING RAW GOLDEN DATASETS DOWNLOAD TO app/data/raw_data/")
    print("==================================================")
    download_nam_syntax_dataset()
    download_vlegal_raw_dataset()
    print("==================================================")
    print("DOWNLOAD COMPLETE.")
    print("==================================================")
