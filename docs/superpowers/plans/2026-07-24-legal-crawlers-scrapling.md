# Legal Data Crawlers (Scrapling Framework) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build resilient Scrapling crawlers for `vbpl.vn`, `vietlaw.quochoi.vn`, and `moj.gov.vn`. Store output separately in 3 distinct folders under `data/scrapling_raw/`. Perform initial sample test crawls, verify extracted schemas, and report findings to the user for approval before running full dataset crawling.

**Architecture:** Implement modular Scrapling crawlers under `app/ingestion/crawlers/` using `StealthyFetcher` and `Fetcher`. Save raw data into dedicated subdirectories (`data/scrapling_raw/vbpl/`, `data/scrapling_raw/vietlaw/`, `data/scrapling_raw/moj/`). Provide test verification scripts and a reporting checkpoint prior to full bulk crawl launch.

**Tech Stack:** Python 3.10+, Scrapling 0.4.11+, Pydantic v2, Pytest.

## Global Constraints

- Must separate output data into 3 distinct folders:
  - `data/scrapling_raw/vbpl/`
  - `data/scrapling_raw/vietlaw/`
  - `data/scrapling_raw/moj/`
- **MANDATORY CHECKPOINT**: Must perform test crawl (1-5 URLs per site), extract schemas, inspect outputs, and **REPORT TO USER FOR APPROVAL** before triggering any full bulk crawl.

---

### Task 1: Core Scrapling Base & Directory Structure Setup

**Files:**
- Create: `app/ingestion/schemas.py`
- Create: `app/ingestion/scrapling_base.py`
- Test: `tests/test_scrapling_base.py`

**Interfaces:**
- Consumes: Scrapling library (`Fetcher`, `StealthyFetcher`, `Adaptor`)
- Produces: `BaseLegalCrawler` abstract class, `LegalDocumentSchema`, and directory initialization for `data/scrapling_raw/{vbpl,vietlaw,moj}`.

- [ ] **Step 1: Write failing unit test for `LegalDocumentSchema` & output directory resolver**

```python
import os
import pytest
from app.ingestion.schemas import LegalDocumentSchema
from app.ingestion.scrapling_base import get_output_dir_for_source

def test_legal_document_schema_and_paths():
    doc = LegalDocumentSchema(
        source_id="12345",
        source="vbpl.vn",
        url="https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=12345",
        title="Luật Công chứng 2024",
        full_text="Nội dung luật..."
    )
    assert doc.source == "vbpl.vn"
    out_dir = get_output_dir_for_source("vbpl.vn")
    assert out_dir.endswith(os.path.join("data", "scrapling_raw", "vbpl"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scrapling_base.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `schemas.py` and `scrapling_base.py`**

```python
# app/ingestion/schemas.py
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

class LegalDocumentSchema(BaseModel):
    source_id: str
    source: str
    url: str
    title: str
    document_type: Optional[str] = ""
    official_number: Optional[str] = ""
    issued_date: Optional[str] = ""
    effective_date: Optional[str] = ""
    enforced_date: Optional[str] = ""
    expiry_date: Optional[str] = ""
    issuing_body: Optional[str] = ""
    signer: Optional[str] = ""
    status: Optional[str] = ""
    full_text: str
    html_text: Optional[str] = ""
    attributes: Dict[str, Any] = Field(default_factory=dict)
    relations: Dict[str, List[str]] = Field(default_factory=dict)
```

```python
# app/ingestion/scrapling_base.py
import os
from abc import ABC, abstractmethod
from typing import Optional
from scrapling import Fetcher, StealthyFetcher
from app.ingestion.schemas import LegalDocumentSchema

BASE_RAW_DIR = os.path.join("data", "scrapling_raw")

def get_output_dir_for_source(source: str) -> str:
    folder_map = {
        "vbpl.vn": "vbpl",
        "vietlaw.quochoi.vn": "vietlaw",
        "moj.gov.vn": "moj"
    }
    subfolder = folder_map.get(source, "others")
    path = os.path.join(BASE_RAW_DIR, subfolder)
    os.makedirs(path, exist_ok=True)
    return path

class BaseLegalCrawler(ABC):
    def __init__(self, use_stealth: bool = True, timeout: int = 30000):
        self.use_stealth = use_stealth
        self.timeout = timeout

    def fetch_page(self, url: str, solve_cloudflare: bool = True):
        if self.use_stealth:
            fetcher = StealthyFetcher()
            return fetcher.fetch(url, solve_cloudflare=solve_cloudflare, timeout=self.timeout)
        else:
            fetcher = Fetcher()
            return fetcher.fetch(url, timeout=self.timeout)

    @abstractmethod
    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scrapling_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/schemas.py app/ingestion/scrapling_base.py tests/test_scrapling_base.py
git commit -m "feat(ingestion): add LegalDocumentSchema and output folder routing"
```

---

### Task 2: Refactored `vbpl.vn` Scrapling Crawler

**Files:**
- Create: `app/ingestion/crawlers/vbpl_crawler.py`
- Test: `tests/test_vbpl_crawler.py`

**Interfaces:**
- Consumes: `BaseLegalCrawler`, `LegalDocumentSchema`, Scrapling `Adaptor`
- Produces: `VBPLCrawler.parse_document(url) -> LegalDocumentSchema`

- [ ] **Step 1: Write failing test for `VBPLCrawler`**

```python
import pytest
from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler

def test_vbpl_crawler_parse_mock():
    crawler = VBPLCrawler(use_stealth=False)
    url = "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=130000"
    doc = crawler.parse_document_from_html(
        url=url,
        html_content="<div class='box-map'><a>Root</a><a>Luật Đất đai 2024</a></div><div class='fulltext'><div>Header</div><div>Nội dung luật...</div></div>",
        attr_html="<div class='vbProperties'><table><tr><td class='label'>Số ký hiệu</td><td>31/2024/QH15</td></tr></table></div>",
        schema_html="<div class='vbLuocdo'><div class='luocdo'><div class='title'><a>Văn bản căn cứ</a></div><a class='jTips' href='/tw/Pages/vbpq-todan.aspx?ItemID=100'>Luật 2013</a></div></div>"
    )
    assert doc.title == "Luật Đất đai 2024"
    assert doc.official_number == "31/2024/QH15"
    assert "Văn bản căn cứ" in doc.relations
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vbpl_crawler.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `VBPLCrawler`**

```python
# app/ingestion/crawlers/vbpl_crawler.py
import re
from typing import Optional
from scrapling import Adaptor
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

class VBPLCrawler(BaseLegalCrawler):
    def parse_document_from_html(self, url: str, html_content: str, attr_html: str = "", schema_html: str = "") -> LegalDocumentSchema:
        page = Adaptor(html_content)
        breadcrumbs = page.css(".box-map a::text").get_all()
        title = breadcrumbs[-1].strip() if breadcrumbs else "Văn bản pháp luật"
        
        content_nodes = page.css(".fulltext div").get_all()
        full_text = " ".join([Adaptor(node).css("::text").get_all_joined() for node in content_nodes]) if content_nodes else page.css("::text").get_all_joined()

        atts = {}
        if attr_html:
            attr_page = Adaptor(attr_html)
            rows = attr_page.css(".vbProperties table tr")
            for row in rows:
                label = row.css(".label::text").get("").strip()
                val = row.css("td:not(.label)::text").get("").strip()
                if label and val:
                    atts[label] = val

        relations = {}
        if schema_html:
            schema_page = Adaptor(schema_html)
            blocks = schema_page.css(".luocdo")
            for block in blocks:
                rel_title = block.css(".title a::text").get("").strip()
                links = [f"https://vbpl.vn{a.attrib.get('href', '')}" for a in block.css("a.jTips")]
                if rel_title and links:
                    relations[rel_title] = links

        item_id = re.search(r"ItemID=(\d+)", url)
        source_id = item_id.group(1) if item_id else "unknown"

        return LegalDocumentSchema(
            source_id=source_id,
            source="vbpl.vn",
            url=url,
            title=title,
            official_number=atts.get("Số ký hiệu", ""),
            issued_date=atts.get("Ngày ban hành", ""),
            effective_date=atts.get("Ngày có hiệu lực", ""),
            expiry_date=atts.get("Ngày hết hiệu lực", ""),
            issuing_body=atts.get("Cơ quan ban hành", ""),
            full_text=full_text,
            html_text=html_content,
            attributes=atts,
            relations=relations
        )

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        res = self.fetch_page(url)
        item_id = re.search(r"ItemID=(\d+)", url)
        if not item_id:
            return None
        sid = item_id.group(1)
        
        attr_res = self.fetch_page(f"https://vbpl.vn/tw/Pages/vbpq-thuoctinh.aspx?ItemID={sid}")
        schema_res = self.fetch_page(f"https://vbpl.vn/TW/Pages/vbpq-luocdo.aspx?ItemID={sid}")
        
        return self.parse_document_from_html(
            url=url,
            html_content=res.text if res else "",
            attr_html=attr_res.text if attr_res else "",
            schema_html=schema_res.text if schema_res else ""
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vbpl_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/crawlers/vbpl_crawler.py tests/test_vbpl_crawler.py
git commit -m "feat(ingestion): add Scrapling VBPL crawler"
```

---

### Task 3: `vietlaw.quochoi.vn` Scrapling Crawler

**Files:**
- Create: `app/ingestion/crawlers/vietlaw_crawler.py`
- Test: `tests/test_vietlaw_crawler.py`

- [ ] **Step 1: Write failing unit test for `VietlawCrawler`**

```python
import pytest
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler

def test_vietlaw_crawler_parser():
    crawler = VietlawCrawler(use_stealth=False)
    mock_html = """
    <div class="document-detail">
        <h1 class="doc-title">Luật Ban hành văn bản quy phạm pháp luật</h1>
        <div class="doc-number">Số: 80/2015/QH13</div>
        <div class="doc-content"><p>Điều 1. Phạm vi điều chỉnh...</p></div>
    </div>
    """
    doc = crawler.parse_document_from_html("https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID=999", mock_html)
    assert doc.source == "vietlaw.quochoi.vn"
    assert doc.title == "Luật Ban hành văn bản quy phạm pháp luật"
    assert doc.official_number == "80/2015/QH13"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vietlaw_crawler.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `VietlawCrawler`**

```python
# app/ingestion/crawlers/vietlaw_crawler.py
import re
from typing import Optional
from scrapling import Adaptor
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

class VietlawCrawler(BaseLegalCrawler):
    def parse_document_from_html(self, url: str, html_content: str) -> LegalDocumentSchema:
        page = Adaptor(html_content)
        title = page.css(".doc-title::text", "h1::text", ".title::text").get("Văn bản Quốc hội").strip()
        num_text = page.css(".doc-number::text", ".number::text").get("").strip()
        official_number = re.sub(r"Số:\s*", "", num_text)
        
        content = page.css(".doc-content", ".fulltext", "#content").get_all_joined()
        if not content:
            content = page.css("body").get_all_joined()

        item_id = re.search(r"ItemID=(\d+)", url)
        sid = item_id.group(1) if item_id else "unknown"

        return LegalDocumentSchema(
            source_id=sid,
            source="vietlaw.quochoi.vn",
            url=url,
            title=title,
            official_number=official_number,
            full_text=content,
            html_text=html_content
        )

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        res = self.fetch_page(url)
        if not res:
            return None
        return self.parse_document_from_html(url, res.text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vietlaw_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/crawlers/vietlaw_crawler.py tests/test_vietlaw_crawler.py
git commit -m "feat(ingestion): add Vietlaw Quốc hội Scrapling crawler"
```

---

### Task 4: `moj.gov.vn` Scrapling Crawler

**Files:**
- Create: `app/ingestion/crawlers/moj_crawler.py`
- Test: `tests/test_moj_crawler.py`

- [ ] **Step 1: Write failing unit test for `MOJCrawler`**

```python
import pytest
from app.ingestion.crawlers.moj_crawler import MOJCrawler

def test_moj_crawler_parser():
    crawler = MOJCrawler(use_stealth=False)
    mock_html = """
    <div class="portlet-content">
        <h2 class="article-title">Thông tư hướng dẫn thi hành Luật X</h2>
        <div class="article-date">Ngày đăng: 15/05/2024</div>
        <div class="article-body"><p>Bộ Tư pháp hướng dẫn như sau...</p></div>
    </div>
    """
    doc = crawler.parse_document_from_html("https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID=888", mock_html)
    assert doc.source == "moj.gov.vn"
    assert doc.title == "Thông tư hướng dẫn thi hành Luật X"
    assert doc.issued_date == "15/05/2024"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_moj_crawler.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `MOJCrawler`**

```python
# app/ingestion/crawlers/moj_crawler.py
import re
from typing import Optional
from scrapling import Adaptor
from app.ingestion.scrapling_base import BaseLegalCrawler
from app.ingestion.schemas import LegalDocumentSchema

class MOJCrawler(BaseLegalCrawler):
    def parse_document_from_html(self, url: str, html_content: str) -> LegalDocumentSchema:
        page = Adaptor(html_content)
        title = page.css(".article-title::text", ".title::text", "h2::text").get("Văn bản Bộ Tư pháp").strip()
        date_text = page.css(".article-date::text", ".date::text").get("").strip()
        issued_date = re.search(r"\d{2}/\d{2}/\d{4}", date_text)
        issued_str = issued_date.group(0) if issued_date else ""

        body = page.css(".article-body", ".content", ".detail-content").get_all_joined()
        if not body:
            body = page.css("body").get_all_joined()

        item_id = re.search(r"ItemID=(\d+)", url)
        sid = item_id.group(1) if item_id else "unknown"

        return LegalDocumentSchema(
            source_id=sid,
            source="moj.gov.vn",
            url=url,
            title=title,
            issued_date=issued_str,
            full_text=body,
            html_text=html_content
        )

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        res = self.fetch_page(url)
        if not res:
            return None
        return self.parse_document_from_html(url, res.text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_moj_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/crawlers/moj_crawler.py tests/test_moj_crawler.py
git commit -m "feat(ingestion): add MOJ Bộ Tư pháp Scrapling crawler"
```

---

### Task 5: Test Crawl Runner, Multi-Folder Router & Verification Reporting

**Files:**
- Create: `scripts/run_scrapling_crawlers.py`
- Test: `tests/test_crawler_pipeline.py`

**Interfaces:**
- Consumes: Crawlers (`VBPLCrawler`, `VietlawCrawler`, `MOJCrawler`)
- Produces: CLI runner that outputs data into `data/scrapling_raw/{vbpl,vietlaw,moj}/` and generates test crawl report for user approval.

- [ ] **Step 1: Write integration test for directory saving**

```python
import os
import pytest
from scripts.run_scrapling_crawlers import run_crawler_job

def test_run_crawler_job_directories(tmp_path):
    urls = [
        "https://vbpl.vn/tw/Pages/vbpq-todan.aspx?ItemID=130000",
        "https://vietlaw.quochoi.vn/pages/vbpq-toanvan.aspx?ItemID=999",
        "https://moj.gov.vn/qt/vbpl/pages/chi-tiet-van-ban.aspx?ItemID=888"
    ]
    summary = run_crawler_job(urls=urls, is_test_run=True, mock=True)
    assert summary["vbpl.vn"] >= 1
    assert summary["vietlaw.quochoi.vn"] >= 1
    assert summary["moj.gov.vn"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crawler_pipeline.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement `scripts/run_scrapling_crawlers.py` with multi-folder routing**

```python
# scripts/run_scrapling_crawlers.py
import os
import json
import argparse
from typing import List, Dict
from app.ingestion.crawlers.vbpl_crawler import VBPLCrawler
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler
from app.ingestion.crawlers.moj_crawler import MOJCrawler
from app.ingestion.scrapling_base import get_output_dir_for_source
from app.ingestion.schemas import LegalDocumentSchema

def get_crawler_and_source(url: str):
    if "vbpl.vn" in url:
        return VBPLCrawler(), "vbpl.vn"
    elif "quochoi.vn" in url:
        return VietlawCrawler(), "vietlaw.quochoi.vn"
    elif "moj.gov.vn" in url:
        return MOJCrawler(), "moj.gov.vn"
    else:
        raise ValueError(f"Unsupported URL domain: {url}")

def run_crawler_job(urls: List[str], is_test_run: bool = False, mock: bool = False) -> Dict[str, int]:
    summary = {"vbpl.vn": 0, "vietlaw.quochoi.vn": 0, "moj.gov.vn": 0}
    
    for url in urls:
        crawler, source = get_crawler_and_source(url)
        out_dir = get_output_dir_for_source(source)
        
        if mock:
            doc = LegalDocumentSchema(
                source_id="mock_sample",
                source=source,
                url=url,
                title=f"Mock Title for {source}",
                full_text="Sample text..."
            )
        else:
            doc = crawler.parse_document(url)

        if doc:
            filename = f"{doc.source_id}.json"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(doc.model_dump(), f, ensure_ascii=False, indent=2)
            summary[source] += 1

    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Scrapling legal crawlers")
    parser.add_argument("--urls", nargs="+", required=True, help="List of URLs to crawl")
    parser.add_argument("--test", action="store_true", help="Perform sample test crawl only")
    args = parser.parse_args()
    
    summary = run_crawler_job(args.urls, is_test_run=args.test)
    print("Crawl summary:", json.dumps(summary, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crawler_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/run_scrapling_crawlers.py tests/test_crawler_pipeline.py
git commit -m "feat(ingestion): add multi-folder output runner and test verification mode"
```

## Verification Plan & User Reporting Checkpoint

### Automated Tests
- `pytest tests/test_scrapling_base.py -v`
- `pytest tests/test_vbpl_crawler.py -v`
- `pytest tests/test_vietlaw_crawler.py -v`
- `pytest tests/test_moj_crawler.py -v`
- `pytest tests/test_crawler_pipeline.py -v`

### Manual Verification & User Report Protocol
1. Perform test crawl on 1-3 sample URLs per site using `--test`:
   - Output paths generated:
     - `data/scrapling_raw/vbpl/*.json`
     - `data/scrapling_raw/vietlaw/*.json`
     - `data/scrapling_raw/moj/*.json`
2. **USER REPORTING CHECKPOINT**: Read the parsed JSON files, extract schema statistics and sample outputs, and submit a formal report to the user. **DO NOT proceed to full dataset crawling without user's explicit sign-off.**
