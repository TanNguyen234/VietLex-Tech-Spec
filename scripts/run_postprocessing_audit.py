import sys
import os
import json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ingestion.schemas import LegalDocumentSchema
from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline

def main():
    pipeline = LegalPreprocessingPipeline()
    sample_dir = os.path.join(os.path.dirname(__file__), "..", "data", "scrapling_raw", "trial_samples")
    
    samples = ["moj_sample.json", "vbpl_sample.json", "vietlaw_sample.json"]
    
    print("==========================================================")
    print("  RUNNING PIPELINE AUDIT ON REAL CRAWLED TRIAL SAMPLES")
    print("==========================================================")

    for sample in samples:
        path = os.path.join(sample_dir, sample)
        if not os.path.exists(path):
            print(f"Sample file not found: {path}")
            continue

        print(f"\nProcessing {sample}...")
        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        doc = LegalDocumentSchema(**raw_data)
        processed = pipeline.process(doc)
        print(json.dumps(processed.integrity_report.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print(f"-> Processed {sample}: disposition={processed.disposition.value}, chunks={len(processed.chunks)}")

if __name__ == "__main__":
    main()
