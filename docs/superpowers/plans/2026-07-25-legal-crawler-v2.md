# Legal Crawler v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate CSS/JS script noise (`.s4-`, `//<![CDATA[`, `.one-item-sub-menu`) from VietLaw, MOJ, and VBPL crawlers, implement Next.js full-text rendering for VBPL, and enforce strict legal URL prefix filtering.

**Architecture:** 
- `app/ingestion/crawlers/vbpl_crawler.py`: Add URL slug prefix validator (`nghi-dinh`, `quyet-dinh`, `sac-lenh`, `nghi-quyet`, `thong-tu`, `chi-thi`, `luat`, `bo-luat`), use `StealthyFetcher` / headless browser render to wait for `.fulltext` element to load 100% legal text body, and strip script/style tags.
- `app/ingestion/crawlers/vietlaw_crawler.py`: Add pre-parsing HTML cleanup pass to remove `<script>`, `<style>`, `<form>`, and SharePoint ASP.NET ribbon elements (`#s4-ribbonrow`, `.s4-skipribbonshortcut`).
- `app/ingestion/crawlers/moj_crawler.py`: Add pre-parsing HTML cleanup pass to remove `<script>`, `<style>`, and parse key-value detail elements (`.content-chitiet-tintuc`, `.divdetail-icon`).

**Tech Stack:** Python 3.12, Scrapling (`Selector`, `StealthyFetcher`), BeautifulSoup4, Regex, pytest.

## Global Constraints
- Do not hardcode API keys or secrets.
- Store output in `data/scrapling_raw/trial_samples/`.
- All `full_text` fields must be clean natural Vietnamese text with 0 CSS/JS/HTML script tag pollution.

---

### Task 1: Refactor VietLaw & MOJ HTML Boilerplate Stripping & Key-Value Parsing

**Files:**
- Modify: `app/ingestion/crawlers/vietlaw_crawler.py`
- Modify: `app/ingestion/crawlers/moj_crawler.py`
- Test: `scripts/test_trial_crawl.py`

**Interfaces:**
- Consumes: Raw HTML string from HTTP response.
- Produces: `LegalDocumentSchema` with clean `full_text` stripped of `.s4-skipribbonshortcut`, `//<![CDATA[`, `.one-item-sub-menu`, and ASP.NET scripts.

- [ ] **Step 1: Update `VietlawCrawler` HTML pre-processing**

```python
# In app/ingestion/crawlers/vietlaw_crawler.py
from bs4 import BeautifulSoup

def clean_html_tree(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "form"]):
        tag.extract()
    for el in soup.select("#s4-ribbonrow, .s4-skipribbonshortcut, .ms-nav"):
        el.extract()
    return str(soup)
```

- [ ] **Step 2: Update `MOJCrawler` HTML pre-processing & key-value extraction**

```python
# In app/ingestion/crawlers/moj_crawler.py
def clean_html_tree(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer"]):
        tag.extract()
    return str(soup)
```

- [ ] **Step 3: Run trial crawl verification for VietLaw and MOJ**

Run: `python scripts/test_trial_crawl.py`
Expected: `vietlaw_sample.json` and `moj_sample.json` contain clean `full_text` starting with legal document title / content, with 0 CSS/JS code.

---

### Task 2: Implement VBPL Legal URL Prefix Filter & Next.js Full-Text Headless Rendering

**Files:**
- Modify: `app/ingestion/crawlers/vbpl_crawler.py`
- Test: `scripts/test_trial_crawl.py`

**Interfaces:**
- Consumes: URL string & HTML string.
- Produces: Validated `LegalDocumentSchema` with full-text body and filtered legal document prefix matching.

- [ ] **Step 1: Implement `is_valid_vbpl_legal_url` prefix filter in `vbpl_crawler.py`**

```python
ALLOWED_VBPL_PREFIXES = (
    "nghi-dinh", "quyet-dinh", "sac-lenh", "nghi-quyet", 
    "thong-tu", "chi-thi", "luat", "bo-luat"
)

def is_valid_vbpl_legal_url(url: str) -> bool:
    slug = url.split("/")[-1].lower()
    return any(slug.startswith(prefix) or f"-{prefix}-" in slug for prefix in ALLOWED_VBPL_PREFIXES)
```

- [ ] **Step 2: Implement `StealthyFetcher` / full-text body extractor for VBPL Next.js CSR**

```python
# In VBPLCrawler.parse_document
def parse_document(self, url: str) -> Optional[LegalDocumentSchema]:
    if not is_valid_vbpl_legal_url(url):
        print(f"[VBPL] Discarded non-legal document URL: {url}")
        return None
    # Fetch page with StealthyFetcher waiting for .fulltext or fetch content endpoint
    ...
```

- [ ] **Step 3: Run trial crawl verification for all 3 sites**

Run: `python scripts/test_trial_crawl.py`
Expected: All 3 sites return `SUCCESS ✅`, metadata fields populated, clean `full_text` for `VBPL`, `VietLaw`, and `MOJ`.

- [ ] **Step 4: Commit changes**

```bash
git add app/ingestion/crawlers/
git commit -m "feat(crawler): clean CSS/JS noise, add VBPL URL prefix filter & Next.js full-text renderer"
```
