# Legal Crawler v2 Design Specification

> **Status:** Draft for User Approval  
> **Date:** 2026-07-25  
> **Authors:** AI Agent & Legal RAG Engineering Team  

---

## 🎯 Goal
Eliminate inline CSS/JS script noise (`.s4-skipribbonshortcut`, `var theForm`, `.one-item-sub-menu`) from crawled legal documents (`VietLaw`, `MOJ`, `VBPL`), extract full-text legal document bodies from Next.js rendered pages on `VBPL`, filter out non-legal document URLs using strict legal prefix rules, and extract key-value metadata attributes into clean `LegalDocumentSchema` fields.

---

## 🏛️ System Architecture & Site-Specific Crawler Rules

### 1. VBPL Crawler (`app/ingestion/crawlers/vbpl_crawler.py`)
- **URL Filtering**: Strict prefix matching on URL slugs.
  - **Allowed Prefixes**: `nghi-dinh`, `quyet-dinh`, `sac-lenh`, `nghi-quyet`, `thong-tu`, `chi-thi`, `luat`, `bo-luat`.
  - **Action**: Discard any harvested URL whose slug does not match one of these prefixes.
- **Rendering & Full-Text Fetching**:
  - VBPL uses Next.js Client-Side Rendering (CSR). Initial static GET returns an HTML shell with `"Đang tải dữ liệu..."`.
  - Use `StealthyFetcher` / headless rendering with `page.wait_for_selector(".fulltext", timeout=5000)` or fallback to Next.js API / tab requests to load full document text body (Điều 1, Điều 2, ...).
- **Metadata Extraction**:
  - Extract `official_number`, `document_type`, `issued_date`, `issuing_body`, and `status` from Schema.org `Legislation` script tag (`type="application/ld+json"`).
- **Boilerplate Stripping**: Extract `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`, `<header>`, `<footer>`, Next.js hydration chunks (`self.__next_f`), and frame-busting code before building `full_text`.

### 2. VietLaw Crawler (`app/ingestion/crawlers/vietlaw_crawler.py`)
- **URL Matching**: Retain existing URL discovery as VietLaw endpoints do not rely on URL prefixes (`ItemID=...`).
- **Boilerplate Stripping**:
  - Remove all `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<svg>`, `<header>`, `<footer>`, `<form>`, and SharePoint ASP.NET ribbon elements (`#s4-ribbonrow`, `.s4-skipribbonshortcut`, `aspnetForm`).
- **Metadata & Text Extraction**:
  - Extract `official_number` via regex from document header or title.
  - Parse content node `.doc-content`, `.fulltext`, or clean `body` text after stripping script/style tags.

### 3. MOJ Crawler (`app/ingestion/crawlers/moj_crawler.py`)
- **URL Filtering**: Keep valid portal article endpoints matching `.html$` and numeric news IDs.
- **Key-Value Attribute Extraction**:
  - Parse metadata fields from MOJ detail header blocks (`.content-chitiet-tintuc`, `.divdetail-icon`, `.article-date`).
  - Extract `issued_date`, `official_number`, and `title`.
- **Boilerplate Stripping**:
  - Strip all `<style>` and `<script>` elements before extracting `.content-noidung` or `.news-detail` body text to prevent `.one-item-sub-menu { color: #333;` from bleeding into `full_text`.

---

## 🧪 Verification & Acceptance Criteria
1. **Trial Test**: Re-running `python scripts/test_trial_crawl.py` produces clean `vbpl_sample.json`, `vietlaw_sample.json`, and `moj_sample.json`.
2. **Zero Script/CSS Noise**: `full_text` in all 3 sample files contains 0 instances of `.s4-`, `//<![CDATA[`, `.one-item-sub-menu`, or `document.forms`.
3. **VBPL Full Text**: `vbpl_sample.json` contains full legal document content beyond just the metadata header.
4. **URL Prefix Filter**: Non-matching VBPL URLs are logged and skipped.
