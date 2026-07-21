import os
import gzip
import json

def test_raw_datalake_document_structure():
    raw_dir = "app/data/raw_data"
    files = [f for f in os.listdir(raw_dir) if f.endswith(".json.gz")]
    assert len(files) > 0, "Raw Data Lake dataset files missing"
    
    sample_path = os.path.join(raw_dir, files[0])
    with gzip.open(sample_path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
        
    assert "source_id" in doc
    assert "title" in doc
    assert "full_text" in doc
    assert "html_text" in doc
    assert "attribute" in doc
    assert len(doc["full_text"]) > 0
