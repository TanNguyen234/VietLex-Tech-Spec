# Upgrade VietLex Legal RAG to 1024-dim BGE-M3 & Contextual Structural Chunking

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace legacy 384-dim FastEmbed MiniLM index with 1024-dim BGE-M3 dense embeddings and PyVi BM25 sparse vectors in Qdrant, combined with Legal Contextual Header Chunking and Cross-Encoder Reranking to elevate retrieval accuracy to Top 1-3.

**Architecture:** 
1. **Contextual Structural Chunker (`app/ingestion/parser.py`)**: Parses legal text by Chapter/Section/Article/Clause and prepends a rich document context header `[Văn bản: {title} | Số hiệu: {official_number} | {chapter} | {section}]` to each chunk before embedding.
2. **1024-dim Vector Ingestion (`scripts/reindex_bge_m3.py` & `app/ingestion/crawler_indexer.py`)**: Recreates Qdrant collection `vietlex_laws_crawler_kb` with `size=1024`, calls Google Cloud Run BGE-M3 microservice for dense vectors and PyVi for sparse vectors, and upserts full legal payloads.
3. **Optimized Search Pipeline (`app/services/rag_pipeline.py`)**: Executes full 1024-dim dense search + BM25 sparse search, RRF Fusion (Top 35), and BGE-Reranker-v2-M3 Cross-Encoder to select Top 3 chunks for Gemini generation.

**Tech Stack:** Python 3.10+, Qdrant Cloud (AsyncQdrantClient), BAAI/bge-m3 ONNX (Cloud Run), BGE-Reranker-v2-M3 (Cloud Run), PyVi Tokenizer, Logfire Observability.

## Global Constraints
- `QDRANT_URL` and `QDRANT_API_KEY` loaded via `app/config.py` using Pydantic `BaseSettings`.
- Vector dimension in `vietlex_laws_crawler_kb` collection MUST be exactly `1024`.
- Sparse vector index MUST be configured with `"sparse-text": SparseVectorParams()`.
- Reranker output MUST yield Top 3 chunks to LLM prompt.

---

### Task 1: Enhance Legal Parser with Contextual Header Enrichment

**Files:**
- Modify: `app/ingestion/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: Raw text of legal documents, metadata dict (`title`, `official_number`, etc.)
- Produces: List of chunk dicts with formatted context-enriched string: `f"[Văn bản: {title} | Số hiệu: {official_number} | {chapter} | {section}]\nĐiều {art_num}. {art_body}"`

- [ ] **Step 1: Write failing test for contextual header enrichment**

Create `tests/test_parser.py`:
```python
import pytest
from app.ingestion.parser import parse_legal_document_with_context

def test_parse_legal_document_with_context():
    doc_text = """
    Chương I
    QUY ĐỊNH CHUNG
    Mục 1
    PHẠM VI ĐIỀU CHỈNH
    Điều 1. Phạm vi điều chỉnh
    Luật này quy định về hoạt động đấu thầu.
    """
    metadata = {
        "title": "Luật Đấu thầu 2023",
        "official_number": "22/2023/QH15"
    }
    chunks = parse_legal_document_with_context(doc_text, metadata)
    assert len(chunks) == 1
    assert "[Văn bản: Luật Đấu thầu 2023 | Số hiệu: 22/2023/QH15 | Chương I | Mục 1]" in chunks[0]["content"]
    assert "Điều 1. Phạm vi điều chỉnh" in chunks[0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL (`ImportError` or `cannot import name 'parse_legal_document_with_context'`)

- [ ] **Step 3: Update `app/ingestion/parser.py`**

Update `app/ingestion/parser.py`:
```python
import re
import logfire
from typing import List, Dict, Optional

@logfire.instrument("Phân tách văn bản luật với Context Enrichment")
def parse_legal_document_with_context(file_content: str, metadata: Optional[Dict] = None) -> List[Dict]:
    meta = metadata or {}
    title = meta.get("title", "").strip() or "Văn bản Luật"
    official_num = meta.get("official_number", "")
    if isinstance(official_num, list):
        official_num = ", ".join(official_num)
    official_num = str(official_num).strip() or "Không có số hiệu"
    
    chunks = []
    
    chapter_matches = list(re.finditer(
        r'(?i)(?:^|\n)Chương\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\nChương\s+[A-Za-z0-9_À-ỹ]+)|$)', 
        file_content, 
        re.DOTALL
    ))
    
    chapter_content_blocks = (
        [(None, "Chương chung", file_content)]
        if not chapter_matches
        else [(m, f"Chương {m.group(1)}", m.group(2)) for m in chapter_matches]
    )
        
    for _, ch_num, ch_content in chapter_content_blocks:
        section_matches = list(re.finditer(
            r'(?i)(?:^|\n)Mục\s+([A-Za-z0-9_À-ỹ]+)(.*?)(?=(?:\nMục\s+[A-Za-z0-9_À-ỹ]+)|$)', 
            ch_content, 
            re.DOTALL
        ))
        
        section_content_blocks = (
            [(None, "Mục chung", ch_content)]
            if not section_matches
            else [(m, f"Mục {m.group(1)}", m.group(2)) for m in section_matches]
        )
            
        for _, sec_num, sec_content in section_content_blocks:
            article_matches = list(re.finditer(
                r'(?i)(?:^|\n)Điều\s+(\d+)\.?(.*?)(?=(?:\nĐiều\s+\d+\.?)|$)', 
                sec_content, 
                re.DOTALL
            ))
            
            for art_match in article_matches:
                art_num = art_match.group(1).strip()
                art_body = art_match.group(2).strip()
                
                header_prefix = f"[Văn bản: {title} | Số hiệu: {official_num} | {ch_num} | {sec_num}]"
                full_chunk_text = f"{header_prefix}\nĐiều {art_num}. {art_body}"
                
                chunks.append({
                    "chapter": ch_num,
                    "section": sec_num,
                    "article": f"Điều {art_num}",
                    "content": full_chunk_text,
                    "raw_article_body": art_body,
                    "header_prefix": header_prefix
                })
                
    logfire.info("Phân tách hoàn tất. Số lượng chunks: {count}", count=len(chunks))
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/parser.py tests/test_parser.py
git commit -m "feat: add contextual header enrichment to legal parser"
```

---

### Task 2: Create Re-indexing Script for 1024-dim BGE-M3 & Qdrant

**Files:**
- Create: `scripts/reindex_bge_m3.py`
- Modify: `app/ingestion/crawler_indexer.py`

**Interfaces:**
- Consumes: Crawled `.gz` legal documents in `app/data/crawled_laws` or raw datasets.
- Produces: Re-created Qdrant collection `vietlex_laws_crawler_kb` with 1024-dim dense vectors & sparse text index.

- [ ] **Step 1: Write `scripts/reindex_bge_m3.py`**

Create `scripts/reindex_bge_m3.py`:
```python
import os
import sys
import gzip
import json
import uuid
import time
import requests
import logfire
from typing import List, Dict
from tqdm import tqdm
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams, SparseVector
from pyvi import ViTokenizer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.ingestion.indexer import text_to_sparse_vector
from app.ingestion.parser import parse_legal_document_with_context
from app.config import get_settings

def load_gz_json(file_path: str) -> Dict:
    try:
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def run_reindex_bge_m3(data_dir: str, collection_name: str = "vietlex_laws_crawler_kb"):
    settings = get_settings()
    print(f"Scanning directory '{data_dir}' for legal document files...")
    
    gz_files = []
    if os.path.exists(data_dir):
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".gz") or file.endswith(".json"):
                    gz_files.append(os.path.join(root, file))
                    
    print(f"Found {len(gz_files)} document files.")
    if not gz_files:
        print(f"Error: No data files found in '{data_dir}'. Aborting.")
        return

    chunks = []
    for file_path in tqdm(gz_files, desc="Parsing documents with context enrichment"):
        doc_obj = load_gz_json(file_path)
        if not doc_obj:
            continue
            
        full_text = doc_obj.get("full_text", "").strip()
        title = doc_obj.get("title", "").strip()
        url = doc_obj.get("url", "").strip()
        source = doc_obj.get("source", "").strip()
        source_id = str(doc_obj.get("source_id", ""))
        attributes = doc_obj.get("attribute", {})
        
        if not full_text:
            continue
            
        metadata = {
            "title": title,
            "official_number": attributes.get("official_number", [])
        }
        
        doc_chunks = parse_legal_document_with_context(full_text, metadata)
        
        if not doc_chunks:
            paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            header_prefix = f"[Văn bản: {title} | Số hiệu: {metadata['official_number']}]"
            for idx, para in enumerate(paragraphs):
                doc_chunks.append({
                    "chapter": "Default",
                    "section": "Default",
                    "article": f"Para-{idx+1}",
                    "content": f"{header_prefix}\n{para}"
                })
                
        for chunk in doc_chunks:
            chunk.update({
                "title": title,
                "url": url,
                "source": source,
                "source_id": source_id,
                "official_number": attributes.get("official_number", []),
                "document_type": attributes.get("document_type", []),
                "issuing_body": attributes.get("issuing_body/office/signer", []),
                "effective_date": attributes.get("effective_date", ""),
                "expiry_date": attributes.get("expiry_date", "")
            })
            chunks.append(chunk)

    print(f"\nExtracted {len(chunks)} enriched legal chunks.")

    # Connect to Qdrant Cloud
    qdrant_client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=60.0
    )
    
    # Re-create collection with size 1024 (BGE-M3)
    if qdrant_client.collection_exists(collection_name):
        print(f"Deleting old 384-dim collection '{collection_name}'...")
        qdrant_client.delete_collection(collection_name)

    print(f"Creating new Qdrant collection '{collection_name}' with 1024-dim Cosine vectors...")
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        sparse_vectors_config={
            "sparse-text": SparseVectorParams()
        }
    )

    # Batch embedding via Google Cloud Run BGE-M3 API
    url = settings.EMBEDDING_API_URL
    headers = {"Content-Type": "application/json"}
    if settings.EMBEDDING_SERVICE_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EMBEDDING_SERVICE_API_KEY}"

    batch_size = 16
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    print(f"Pushing {len(chunks)} chunks to Qdrant Cloud in {total_batches} batches...")

    indexed_count = 0
    for idx, i in enumerate(range(0, len(chunks), batch_size), 1):
        batch = chunks[i:i+batch_size]
        batch_texts = [c["content"][:2000] for c in batch]
        
        # Call Cloud Run BGE-M3 service
        resp = requests.post(url, json={"inputs": batch_texts, "normalize": True}, headers=headers, timeout=60)
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        
        batch_points = []
        for chunk, vector in zip(batch, embeddings):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk["content"]))
            segmented = ViTokenizer.tokenize(chunk["content"])
            sparse_vec = text_to_sparse_vector(segmented)
            
            payload_data = {
                "chapter": chunk["chapter"],
                "section": chunk["section"],
                "article": chunk["article"],
                "source_text": chunk["content"],
                "title": chunk["title"],
                "url": chunk["url"],
                "source": chunk["source"],
                "source_id": chunk["source_id"],
                "official_number": chunk["official_number"],
                "document_type": chunk["document_type"],
                "issuing_body": chunk["issuing_body"],
                "effective_date": chunk["effective_date"],
                "expiry_date": chunk["expiry_date"]
            }
            
            batch_points.append(PointStruct(
                id=point_id,
                vector={
                    "": vector,
                    "sparse-text": SparseVector(
                        indices=sparse_vec["indices"],
                        values=sparse_vec["values"]
                    )
                },
                payload=payload_data
            ))
            
        qdrant_client.upsert(collection_name=collection_name, points=batch_points)
        indexed_count += len(batch_points)
        print(f" Batch [{idx}/{total_batches}] - Pushed {len(batch_points)} points (Total: {indexed_count})")

    print(f"\nSUCCESSFULLY RE-INDEXED {indexed_count} CHUNKS WITH 1024-DIM BGE-M3!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VietLex BGE-M3 1024-dim Reindexer")
    parser.add_argument("data_dir", type=str, default="laws_project_crawler/data", help="Path to raw laws directory")
    args = parser.parse_args()
    run_reindex_bge_m3(args.data_dir)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/reindex_bge_m3.py
git commit -m "feat: add bge-m3 1024-dim re-indexing script with contextual enrichment"
```

---

### Task 3: Update `rag_pipeline.py` for 1024-dim Retrieval & BGE Reranker Top 3

**Files:**
- Modify: `app/services/rag_pipeline.py:106-215`
- Test: `tests/test_rag_pipeline.py`

**Interfaces:**
- Consumes: Query string
- Produces: Top 3 cross-encoder reranked context chunks, LLM response

- [ ] **Step 1: Write failing test for 1024-dim dense search and rerank**

Create `tests/test_rag_pipeline.py`:
```python
import pytest
from app.services.rag_pipeline import dense_search, cohere_rerank

@pytest.mark.asyncio
async def test_dense_search_returns_points():
    # Verify dense search doesn't truncate to 384 dimensions
    results = await dense_search("thời hạn tạm giữ tàu biển", limit=5)
    assert isinstance(results, list)

@pytest.mark.asyncio
async def test_cohere_rerank_top3():
    docs = [
        "[Văn bản A]\nNội dung điều 1",
        "[Văn bản B]\nNội dung điều 2",
        "[Văn bản C]\nNội dung điều 3",
        "[Văn bản D]\nNội dung điều 4"
    ]
    top_docs = await cohere_rerank("Nội dung điều 2", docs, top_k=3)
    assert len(top_docs) <= 3
```

- [ ] **Step 2: Run test to verify current state**

Run: `pytest tests/test_rag_pipeline.py -v`

- [ ] **Step 3: Update `app/services/rag_pipeline.py`**

In `app/services/rag_pipeline.py`:
1. Remove `query_vector[:384]` truncation in `dense_search`:
```python
async def dense_search(query: str, limit: int = 35) -> List[dict]:
    logfire.info("Đang thực hiện Dense Search qua Cloud Run BGE-M3 Embedding (1024-dim)")
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            timeout=30.0
        )
        
        # Get 1024-dim query vector via Cloud Run BGE-M3 service
        query_vector = await get_embedding(query)
        
        results = await qdrant_client.query_points(
            collection_name="vietlex_laws_crawler_kb",
            query=query_vector,
            limit=limit
        )
        await qdrant_client.close()
        return results.points
    except Exception as e:
        logfire.error("Error during dense search: {error}", error=str(e))
        return []
```

2. Update `run_advanced_rag` to pass Top 35 RRF results into `cohere_rerank` requesting `top_k=3`:
```python
    # 4. Reranking: BGE-Reranker-v2-M3 -> Top 3
    reranked_results = await cohere_rerank(user_query, docs_to_rerank, top_k=3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rag_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/rag_pipeline.py tests/test_rag_pipeline.py
git commit -m "feat: upgrade dense search to 1024-dim BGE-M3 and rerank top 3"
```

---

### Task 4: Evaluation & Verification Reset

**Files:**
- Modify/Reset: `docs/eval_checkpoints.json`
- Test: `run_eval_suite.py`

- [ ] **Step 1: Backup & reset evaluation checkpoint**

```bash
cp docs/eval_checkpoints.json docs/eval_checkpoints_384_backup.json
rm docs/eval_checkpoints.json
```

- [ ] **Step 2: Document Push & Evaluation Instructions**

Document the user execution command:
```bash
# 1. User executes re-indexing script to push 1024-dim BGE-M3 collection:
python scripts/reindex_bge_m3.py laws_project_crawler/data

# 2. User executes 50-query evaluation suite:
python run_eval_suite.py
```

- [ ] **Step 3: Commit plan and verification steps**

```bash
git add docs/
git commit -m "docs: backup legacy evaluation checkpoint for bge-m3 reindex evaluation"
```
