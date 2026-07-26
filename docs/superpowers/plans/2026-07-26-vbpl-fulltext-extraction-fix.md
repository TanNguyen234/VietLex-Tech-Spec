# VBPL Next.js Dynamic Full-Text Extraction Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `VbplCrawler` to reliably extract complete Vietnamese legal document text (24,000+ characters) from dynamic Next.js VBPL pages using Playwright stealth browser rendering instead of getting stuck on 310-character static HTML loading shells.

**Architecture:** VBPL (`vbpl.vn`) uses Next.js App Router (RSC), rendering content dynamically client-side. The crawler fallback will use Playwright headless Chromium with custom stealth User-Agent and header configuration to bypass Fortinet WAF block (Attack ID 20000051), execute JavaScript hydration, extract cleaned document inner text, and fall back cleanly to static parsing when necessary.

**Tech Stack:** Python 3.10+, Playwright Async API, BeautifulSoup4, Scrapling, Pytest.

## Global Constraints

- Must preserve `LegalDocumentSchema` data structure (`source_id`, `url`, `title`, `official_number`, `full_text`, `issuing_body`, `issued_date`, `status`).
- Must filter non-legal URLs with `ALLOWED_VBPL_PREFIXES`.
- `full_text` must be >= 1,000 characters for valid legal documents.

---

### Task 1: Add Playwright Async Renderer to VbplCrawler

**Files:**
- Modify: `app/ingestion/crawlers/vbpl_crawler.py`
- Test: `tests/test_vbpl_crawler.py`

**Interfaces:**
- Consumes: `url: str`
- Produces: `LegalDocumentSchema` object containing complete `full_text` (20,000+ characters)

- [ ] **Step 1: Write failing test in `tests/test_vbpl_crawler.py` for full text length**

```python
import pytest
from app.ingestion.crawlers.vbpl_crawler import VbplCrawler

def test_vbpl_crawler_full_text_length():
    crawler = VbplCrawler()
    url = "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-52-2006-nd-cp-ve-phat-hanh-trai-phieu-doanh-nghiep--16181"
    doc = crawler.parse_document(url)
    assert doc is not None
    assert doc.official_number == "52/2006/NĐ-CP"
    assert len(doc.full_text) > 5000, f"Expected full_text > 5000 chars, got {len(doc.full_text)}"
```

- [ ] **Step 2: Run test to verify it fails on 310 chars**

Run: `pytest tests/test_vbpl_crawler.py::test_vbpl_crawler_full_text_length -v`  
Expected: FAIL with `AssertionError: Expected full_text > 5000 chars, got 310`

- [ ] **Step 3: Update `VbplCrawler` to support Playwright stealth rendering**

```python
import asyncio
import re
from typing import Optional
from scrapling import Selector
from app.ingestion.schemas import LegalDocumentSchema
from app.ingestion.crawlers.vietlaw_crawler import VietlawCrawler

ALLOWED_VBPL_PREFIXES = (
    "nghi-dinh", "quyet-dinh", "sac-lenh", "nghi-quyet",
    "thong-tu", "chi-thi", "luat", "bo-luat"
)

class VbplCrawler:
    """Crawler for VBPL (vbpl.vn) legal documents using Playwright dynamic rendering."""
    
    def is_valid_vbpl_legal_url(self, url: str) -> bool:
        match = re.search(r"/chi-tiet/([^/]+)--\d+", url)
        if not match:
            return False
        slug = match.group(1).lower()
        return slug.startswith(ALLOWED_VBPL_PREFIXES)

    def fetch_with_playwright(self, url: str) -> Optional[str]:
        """Render Next.js client-side content with Playwright stealth browser."""
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    locale="vi-VN",
                    extra_http_headers={"Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}
                )
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                
                body_text = page.evaluate("""() => {
                    const selectorsToHide = ['footer', 'header', 'nav', '.Footer_wrapMainFooter__e_pgb'];
                    selectorsToHide.forEach(s => {
                        document.querySelectorAll(s).forEach(el => el.remove());
                    });
                    return document.body.innerText;
                }""")
                browser.close()
                return body_text
        except Exception as e:
            return None

    def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
        if not self.is_valid_vbpl_legal_url(url):
            return None
            
        rendered_text = self.fetch_with_playwright(url)
        if not rendered_text or len(rendered_text) < 1000:
            return None
            
        # Parse metadata
        match_id = re.search(r"--(\d+)$", url.rstrip("/"))
        sid = match_id.group(1) if match_id else "unknown"
        
        match_num = re.search(r"(\d+/\d{4}/[A-Z0-9-]+|\d+/\d{2}/[A-Z0-9-]+)", url)
        official_number = match_num.group(1) if match_num else ""
        
        # Clean text lines
        clean_text = " ".join(rendered_text.split()).strip()
        
        return LegalDocumentSchema(
            source_id=sid,
            source="vbpl.vn",
            url=url,
            title=f"Văn bản VBPL {official_number}".strip(),
            official_number=official_number,
            full_text=clean_text,
            html_text=""
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vbpl_crawler.py::test_vbpl_crawler_full_text_length -v`  
Expected: PASS (full_text > 24,000 chars)

- [ ] **Step 5: Commit**

```bash
git add app/ingestion/crawlers/vbpl_crawler.py tests/test_vbpl_crawler.py
git commit -m "fix(crawler): Upgrade VbplCrawler to use Playwright stealth rendering for 24k+ char full-text extraction"
```

---

### Task 2: Re-run Live Trial Crawl Script and Update Verification Samples

**Files:**
- Modify: `scripts/test_trial_crawl.py`
- Modify: `data/scrapling_raw/trial_samples/vbpl_sample.json`

- [ ] **Step 1: Execute 3-Site Live Trial Crawl Script**

Run: `python scripts/test_trial_crawl.py`  
Expected: `[VBPL] Status: SUCCESS ✅ | Text: ~24,358 chars`

- [ ] **Step 2: Verify `vbpl_sample.json` contents**

Check `data/scrapling_raw/trial_samples/vbpl_sample.json` line `full_text` length >= 20,000.

- [ ] **Step 3: Commit updated samples and script**

```bash
git add scripts/test_trial_crawl.py data/scrapling_raw/trial_samples/vbpl_sample.json
git commit -m "test(crawler): Update trial samples with 24k+ char clean VBPL document text"
```
