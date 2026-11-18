# Spec: VietLex V4 Full-Stack Architecture & Product Upgrade

**Date:** 2026-11-18  
**Branch:** `feat/vietlex-v4-fullstack-upgrade`  
**Intent Source:** [`docs/intent/vietlex-fullstack-upgrade.md`](../../intent/vietlex-fullstack-upgrade.md)

---

## 0. Capability Map & Module Build Order

Because this upgrade spans four independently testable subsystems, work is decomposed into four explicit capability modules with one-way dependencies:

| Module ID | Responsibility | Depends On |
| :--- | :--- | :--- |
| `mod-1-server-providers` | Multi-provider LLM router (`Vertex`, `Gemini Direct`, `Groq`, `OpenRouter`, `NVIDIA`, `OmniGate`), dev/test/admin unrestricted mode while preserving public user quotas, `ReviewerDemoMiddleware` concurrency/IP fixes, per-`(provider, model)` cooldowns, JSON-mode & thinking-budget normalization, Semantic Cache restoration after Input Guardrail, Docker/Vercel startup fixes. | — |
| `mod-2-tavily-web-rag` | `TavilyClient` (`Search` + `Extract` over `httpx` + `system_ssl_context()`, supporting both `TAVILY_API` and `TAVILY_API_KEY`), Two-Tier Legal Provenance (`Tier-1` official `.gov.vn` evidence + HTTP-403 rescue; `Tier-2` semantic discovery & validity-status pivot), removal of the post-retrieval LLM bypass/context-wipeout trap, and fixes for the 4 web/PDF reader bugs (`"khối lượng"` vs `"lương"`, `DEEP_INSPECTION_LIMIT`, multi-window PDF article retention, unified domain allowlist). | `mod-1-server-providers` |
| `mod-3-corpus-reindex` | Free-Tier Qdrant Cloud & Supabase storage reclamation + modern normative corpus curation (`Hiến pháp + Luật + Pháp lệnh` 100% uncapped articles + `2015–2026 Nghị định & Nghị quyết TW` uncapped + `2020–2026 Thông tư` bounded), issuance-recency & superseded-status ranking metadata, online body-search integration into RAG fallback, and radical simplification of brittle regex rules in `primary_law_rescue.py`. | `mod-1-server-providers` |
| `mod-4-ui-lawyer-tools` | FastAPI/Jinja SSR + vanilla JS UX & Legal Professional tooling upgrade: real SSE token streaming + Cancel button on `/chat`, fixed chat viewport scrolling & consolidated 1-line provenance disclaimer, Dual-Persona progressive disclosure (clean Citizen Chat vs Technical Inspector), `/search` filter dropdowns & accurate SQL/PostgREST pagination, hierarchical `/documents/{id}` reader (`Phần/Chương/Mục/Điều/Khoản` + client filter + long-article pin), Workspace persistent evidence split-pane, DOCX `<w:numPr>` auto-numbering & table extraction, word-level inline Redline with normalized structural matching, unified auto-queued Batch Contract Review, and styled Vietnamese Legal Memorandum DOCX export. | `mod-1-server-providers`, `mod-2-tavily-web-rag`, `mod-3-corpus-reindex` |

**Build Order:** `mod-1-server-providers` → `mod-2-tavily-web-rag` → `mod-3-corpus-reindex` → `mod-4-ui-lawyer-tools`

---

## 1. Explicit Assumptions

1. **Application Stack:** FastAPI + Jinja2 SSR + vanilla JS (`app/static/js/*.js`) + strict CSP (`script-src 'self'; style-src 'self'`) remains the canonical web stack; no external CDN scripts or SPA build toolchains are introduced.
2. **Environment Keys:** `.env` already provides `TAVILY_API` (we bind both `TAVILY_API` and `TAVILY_API_KEY` via `settings.tavily_api_key`, matching `settings.pinecone_api_key`), Vertex ADC (`.secrets/vertex-adc.json`), `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `QDRANT_URL`/`QDRANT_API_KEY`, `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`, and `MONGO_URL`.
3. **Quota Isolation Policy:** Public/non-admin visitors in `APP_ENV=production` with `REVIEWER_DEMO_MODE=true` keep existing daily/minute quotas (`20/day` personal, `100/day` global, `3/min` user). Admin accounts, local `APP_ENV in {"development", "test"}`, and explicit CLI evaluation/re-index scripts run without demo throttling (`admin` is also exempted from the `3/min` demo cap and `PROVIDER_HTTP_ATTEMPT_LIMIT` defaults to `None`).
4. **Normative Purity in Re-indexing:** `Văn bản hợp nhất` (`VBHN`) is excluded from primary vector indexing when the underlying `Luật` and amending `Luật` are already indexed, because `VBHN` is a reference compilation rather than a standalone normative legal instrument (`văn bản quy phạm pháp luật`) and caused citation/validity errors in prior QA rounds.

---

## 2. Objective & Empirical Free-Tier Capacity Budget

### 2.1 Objective
Transform VietLex into a fast, legally accurate, verifiable Vietnamese Legal AI platform that:
- Answers everyday citizen questions in natural Vietnamese with real-time token streaming (`TTFT < 4s`), accurate current statutory citations, conditions/exceptions, and concrete procedural steps.
- Delivers reliable end-to-end workflows for legal practitioners across statutory research, contract review, redlining, claim verification, and formatted Vietnamese DOCX deliverables.

### 2.2 Measured Free-Tier Storage Budget (Verified Against `clean-v1/content_store.sqlite3`)

| Tier | Scope in Local Clean Store (`518,255` docs) | Valid Docs | Raw UTF-8 | Chunk Policy (`320` words, `32` overlap) | Est. Qdrant Points | Est. Qdrant Disk (`~7.8 KB/pt`) | Est. Supabase TOAST Heap + Indexes |
| :--- | :--- | ---: | ---: | :--- | ---: | ---: | ---: |
| **Tier A** | `Hiến pháp` + `Luật` + `Pháp lệnh` (`1995–2026`, incl. all Codes) | `637` | `55.3 MB` | **100% Uncapped (Every Điều/Khoản)** | `~35,000` | `~273 MB` | `~23 MB` |
| **Tier B** | `Nghị định` (`2015–2026`, incl. `168/2024`, `293/2025`, `74/2024`, `12/2022`) | `1,758` | `155.7 MB` | **100% Uncapped (Every Điều/Khoản)** | `~98,000` | `~765 MB` | `~65 MB` |
| **Tier D** | `Nghị quyết` TW (`Quốc hội`, `UBTVQH`, `Chính phủ`, `HĐTP TANDTC`, `2015–2026`) | `2,296` | `44.9 MB` | **100% Uncapped** | `~28,300` | `~221 MB` | `~20 MB` |
| **Tier E** | `Thông tư` & `TTLT` (`2020–2026`) | `~3,150` | `~175.0 MB` | Full up to `32` chunks/doc (annex-bounded) | `~48,000` | `~375 MB` | `~75 MB` |
| **Total Active** | **Pure Modern Normative Set (`A + B + D + E`)** | **`~7,841`** | **`~430.9 MB`** | **Zero truncation on Laws/Decrees/Resolutions** | **`~209,300`** | **`~1.63 GB`** | **`~183 MB`** |

**Cloud Reclamation Plan (Before Upload):**
- **Supabase (`500 MB` limit):** Drop orphaned `public.legal_body_passages` (`state='building'`, `0` active rows = **`-167.4 MB`**) and 8 unused GIN expression indexes on `public.legal_documents` (**`-43.4 MB`**). Net Supabase usage drops from `373 MB` to **`~185–215 MB` (`~40%` of Free Tier, `>280 MB` free headroom)**.
- **Qdrant Cloud (`4.00 GiB` disk / `1.00 GiB` RAM limit):** Delete dormant `vietlex-legal-rag-v2-pilot-384` (**`-682 MB`**) and reset bloated `vietlex-rerank-staging` WAL segments (**`-405 MB`**); align `vietlex-legal-body-search-v1` to the curated `~7,841`-doc set (`~320 MB` disk, `~165 MiB` RAM). Total Qdrant usage settles at **`~2.10 GiB / 4.00 GiB` disk (`52%`)** and **`~380 MiB / 1,024 MiB` RAM (`37%`)**.
- **Long-Tail Coverage (`510,000+` older/local/post-cutoff instruments):** Handled on-demand in `1.5–4.0s` by **Tavily Two-Tier Search + Extract** (`mod-2-tavily-web-rag`) and legacy Pinecone v1 when explicitly selected.

---

## 3. Architecture & Technical Design by Module

### 3.1 `mod-1-server-providers`: Multi-Provider Gateway, Guardrails, Cache & Demo Quotas
1. **Decoupled Provider Selection (`app/services/direct_llm.py`, `app/evaluation/provider_catalog.py`):**
   - Introduce `LLMRouteSelection(provider: str = "auto", model: str | None = None)` supported by `generate_llm_response_with_metadata` and `stream_llm_response`.
   - Wire all 6 integrated providers into one unified catalog: `google_vertex_ai` (`gemini-3.5-flash`), `gemini` (`gemini-2.5-flash` / `gemini-3.5-flash-lite` ready), `groq` (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b`), `openrouter` (`meta-llama/llama-3.3-70b-instruct`), `nvidia` (`meta/llama-3.3-70b-instruct`), and `omnigate` (`legal-core-model`).
   - **Access Policy:** When `APP_ENV in {"development", "test"}` OR authenticated `user.role == "admin"`, callers (UI model selector, API params, CLI benchmarks) may pick `auto` or any configured provider/model freely. Public non-admin users in `production` use `auto` (server-managed fallback chain) under existing quotas.
   - **Bug Fixes:**
     - Key `_cooldowns` by `(provider, model)` instead of `provider` so a `429` on primary does not skip secondary models on the same provider.
     - Pass `response_format={"type": "json_object"}` (OpenAI-compatible) / `responseMimeType="application/json"` (Gemini Direct) + deterministic markdown-fence stripping for `STRUCTURED_ANALYSIS`.
     - Enforce reasoning-token safe budgets (`max_output_tokens >= 256` or provider-specific `reasoning_effort="low"` / `thinkingConfig={"thinkingBudget": 0}`) on guardrail checks so reasoning models never fail with `MAX_TOKENS` on a `yes/no` classification.
     - Allow `serverless_guardrails.py` to fall back across configured direct providers on transient Vertex `429`/`5xx` instead of throwing away generated answers with `HTTP 503`.
     - Skip Output Guardrail LLM calls when `run_advanced_rag` returns deterministic/static responses (`observed_provider == "none"`).
2. **Semantic Cache Restoration (`app/api/routes.py`, `app/services/semantic_cache.py`):**
   - Run mandatory Input Guardrail **first**; on safe cacheable queries, check `semantic_cache` (`check_semantic_cache`). Only write to `semantic_cache` **after** Output Guardrail approves (`output_safe == True`). Thus mandatory guardrails are 100% respected on every cached answer while restoring fast cache hits!
   - Guard `ensure_semantic_cache_collection()` on startup so missing Pinecone credentials degrade semantic cache gracefully (`disabled`) rather than crashing V3 online startup.
3. **`ReviewerDemoMiddleware` & Packaging Fixes (`app/services/reviewer_demo.py`, `Dockerfile`, `app/server.py`):**
   - Release `self.active_bodies` immediately after reading the request body into `messages` (before `await self.app(scope, replay, send)`), eliminating the global 2-request server lockup!
   - Exempt `admin` users from the `3/min` AI demo bucket (`is_demo_daily_exempt` -> `is_demo_exempt` for personal minute & daily AI limits while keeping global abuse safety).
   - Set `ENV SERVERLESS_ONLINE_ONLY=true` in `Dockerfile` (matching `requirements-demo.lock`) and `app/server.py` so production containers never crash on missing `nemoguardrails`.

### 3.2 `mod-2-tavily-web-rag`: Two-Tier Tavily Search/Extract & Grounded Answer Flow
1. **`TavilyClient` (`app/services/tavily_search.py`):**
   - Built on async `httpx.AsyncClient(verify=system_ssl_context())` (zero extra heavy SDK dependency; full unit-test mockability via `httpx.MockTransport`), supporting `TAVILY_API` and `TAVILY_API_KEY` (`settings.tavily_api_key`).
   - Methods: `search(...)` (`POST https://api.tavily.com/search`) and `extract(...)` (`POST https://api.tavily.com/extract`), instrumented via `record_provider_event(provider="tavily", ...)`.
2. **Two-Tier Legal Provenance (`app/services/web_source_tiers.py`):**
   - **Tier 1 (`official_primary` — Direct Legal Evidence):** Unified allowlist across `deep_research.py` and `trusted_source_reader.py` covering `chinhphu.vn` (all official subdomains), `vbpl.vn`, `quochoi.vn`, `moj.gov.vn` (`vbpl`, `phapdien`), `tandtc.gov.vn`, and `*.gov.vn` official portals. When direct HTTP fetch hits `403` (e.g., `vbpl.vn`) or JS-empty body, `TavilyClient.extract()` retrieves clean Markdown with SHA-256 provenance (`read_method="tavily_extract_tier1"`).
   - **Tier 2 (`legal_discovery_pivot` — Discovery & Validity Hint Only):** `thuvienphapluat.vn`, `luatvietnam.vn`. Used **strictly** to map colloquial Vietnamese queries (e.g. *"vượt đèn đỏ ô tô phạt bao nhiêu"*, *"lương tối thiểu vùng hiện nay"*) to exact `document_number` (`168/2024/NĐ-CP`, `293/2025/NĐ-CP`), target `Điều/Khoản` numbers, and replacement hints (*"Hết hiệu lực / Thay thế bởi..."*). Tier-2 hits pivot immediately to (a) local/Supabase hash-verified full text if `document_id` is in store, or (b) exact-number Tier-1 fetch (`CongBaoClient` + `Tavily search(include_domains=TIER_1)`).
3. **Reader & Post-Retrieval Refusal Fixes:**
   - Fix `"lương"` diacritic collision in `app/services/legal_topic_terms.py` (require accented `r"\blương\b"` check so `"khối lượng"`, `"chất lượng"`, `"số lượng"` never trigger Labor Law).
   - Fix `DEEP_INSPECTION_LIMIT` validation mismatch in `app/services/official_document_reader.py:547` and align `SMART_WORKER_TIMEOUT_SECONDS` with `test_pdf_worker_startup.py`; support multi-window PDF extraction guided by target `Điều` hints (so both penalty and license-revocation articles in `NĐ 168/2024` are extracted!).
   - Fix `deep_official_search.py:160` so the final article in a page window is retained unless visibly truncated mid-sentence.
   - Replace `_requires_verified_effect_evidence`'s LLM-bypassing raw blockquote dump (`rag_pipeline.py:1370-1374`) and `contexts = []` wipeout (`rag_pipeline.py:1058`) with **grounded conditional generation**: the LLM answers directly from the retrieved corpus/Tier-1 provisions, explicitly stating the instrument's issuance/effective clause and a single concise note when post-issuance amendment chains are not exhaustively certified, harmonized with `OUTPUT_PROMPT` (`guardrail_prompts.py`).

### 3.3 `mod-3-corpus-reindex`: Modern Normative Index & Retrieval Ranking
1. **Curated Normative Selector (`app/ingestion/curated_normative_corpus.py`):**
   - Deterministically selects `Tier A + B + D + E` from `clean-v1/content_store.sqlite3` (`ORDER BY issuance_date DESC, document_id DESC`), explicitly including `Hiến pháp` (`2013` + `2025` amendment resolution), all current Codes/Laws/Ordinances, all `2015–2026` Decrees & Central Resolutions, and `2020–2026` Circulars, while excluding `SUPERSEDED_INSTRUMENTS` from default active ranking (or tagging `validity_hint="superseded"` in payload!).
   - Uncaps `max_chunks_per_document` (`None`) for `Tier A, B, D` so **every single Article** of BLDS 2015 (`689/689`), BLTTDS 2015 (`517/517`), BLHS 2015 (`425/425`), Luật Đất đai 2024 (`260/260`), BLLĐ 2019 (`220/220`), Luật BHXH 2024 (`141/141`), NĐ 168/2024 (`55/55`), NĐ 293/2025 (`5/5`) is embedded in Qdrant!
   - Fixes `ARTICLE_RE` in `app/ingestion/legal_text.py` for statutes with indented/inline article headers (like `38/2019/QH14`).
2. **Safe Checkpointed Cloud Migration & Ranking (`scripts/rebuild_curated_free_tier.py`):**
   - Exports pre-migration count/SHA manifest; cleans orphaned Supabase `legal_body_passages` + unused GIN shards and dormant Qdrant `v2-pilot` / `rerank-staging`; reuses existing `gemini-embedding-2` 1024d vectors by `inference_text_sha256` where unchanged and batch-embeds new chunks with SQLite checkpointing; syncs `public.legal_documents` and `vietlex-legal-body-search-v1` to exact 1:1 ID parity.
   - Adds lightweight normativa/recency tie-break + `validity_hint != "superseded"` boost in `vertex_qdrant_retrieval.py` and wires `legal_effect_registry` published overrides into RAG context headers.

### 3.4 `mod-4-ui-lawyer-tools`: Streaming Chat UX, Search/Reader & Lawyer Workspace
1. **Chat UX & Real SSE Streaming (`POST /chat/stream`, `app/templates/index.html`, `app/static/js/vietlex.js`, `app/static/css/vietlex-redesign.css`):**
   - Add `POST /chat/stream` emitting NDJSON/SSE events: `stage` (granular real-time progress: Input Check → Vector Search → Tavily Web Discovery → Reading Official Text → Generating → Citation Check), `delta` (real LLM token chunks), `complete` (verified HTML card + citations + claim support), and `error` (typed actionable message — e.g. login link on `401`, retry timer on `429`), while keeping `POST /chat` backward-compatible for tests/API callers.
   - Add a live **Stop / Hủy** button (`AbortController`) during generation, restore sticky composer + `.chat-history` auto-scroll, add clickable **Suggested Legal Questions** on the empty state (for both citizens & lawyers), fix `+ Mới` auto-titling on first message, collapse developer telemetry (`Trace`, `Retrieval inspector`, `Ragas`) behind a clean `"Chi tiết kỹ thuật"` disclosure, and consolidate the 5 stacked disclaimers into **one crisp provenance footer**.
   - Expose **Provider/Model selector** + **Web Search mode (`Tự động` / `Luôn tìm Tavily` / `Chỉ kho nội bộ`)** in Chat & Workspace when in dev/test or logged in as `admin`.
2. **Legal Search & Statute Reader (`/search`, `/documents/{id}`):**
   - Replace raw text inputs for `legal_type` and `authority` with populated `<select>` / `<datalist>` options + case-insensitive matching; push `sector` filtering into SQL/PostgREST before pagination so page counts and `"Trang tiếp"` are always accurate; clarify `as_of` as an optional registry lookup rather than a misleading `required` field.
   - Upgrade `document_structure.py` and `legal_document.html` to parse `Phần`, `Chương`, `Mục`, `Điều`, `Phụ lục`, add instant client-side article/keyword filter in the sticky TOC, format statute text cleanly (not raw `<pre>`), and allow multi-chunk/sliding-window pinning for articles >4,000 chars.
3. **Lawyer Workspace End-to-End Fixes (`/workspaces/{id}`):**
   - **Persistent Split-Pane Evidence Drawer:** Keep selected evidence & Group A/B toggles accessible across `#analysis`, `#review`, and `#reports` tabs without bouncing back to `#sources`; enable `FREE_WEB_RESEARCH` when Tavily/official providers are verified.
   - **DOCX Parser (`app/services/workspace_documents.py`):** Parse `word/numbering.xml` (`<w:numPr>`) so Word auto-numbered `Điều 1.`, `1.1.` headings and `<w:tbl>` tables are accurately reconstructed into structured clauses.
   - **Word-Level Inline Redline (`app/services/document_redline.py`):** Match clauses by `(structural_number, normalized_title, token_jaccard_similarity)` instead of file-hash `clause_id`, and compute token-level `difflib.SequenceMatcher` inline `<del>`/`<ins>` diffs!
   - **Unified Batch Contract Review (`research-workspace.js`, `full_document_review_routes.py`):** Add `"Chạy toàn bộ các lô"` auto-sequencer with progress bar and aggregate findings across batches into one unified Finding Board with CSV/DOCX Issue Log export.
   - **Professional Vietnamese DOCX Export (`app/services/report_deliverables.py`):** Package complete OOXML (`word/document.xml`, `word/styles.xml`, A4 margins, `Times New Roman` / `Be Vietnam Pro` styling, proper Heading 1/2/3, bullet lists, clickable footnotes/sources) with **standard Vietnamese legal headings** (`BÁO CÁO NGHIÊN CỨU PHÁP LÝ`, `1. Vấn đề pháp lý`, `2. Căn cứ pháp luật`, `3. Phân tích & Áp dụng`, `4. Ngoại lệ & Lưu ý hiệu lực`, `5. Khuyến nghị thực hiện`, `6. Danh mục nguồn đối chiếu`).

---

## 4. Commands, Code Style & Testing Strategy

### 4.1 Executable Commands
```powershell
# Focused unit/service gate (fast TDD loop)
.\.venv\Scripts\python.exe -B -m pytest tests/services/test_tavily_search.py -q

# Frontend JS / DOM contract tests
node --test tests/*.test.cjs

# Lint check on modified files
.\.venv\Scripts\python.exe -m ruff check app tests scripts

# Full provider-free regression suite
.\.venv\Scripts\python.exe -B -m pytest tests -q -m "not live"

# Curated Free-Tier corpus audit & dry-run plan (zero remote writes)
.\.venv\Scripts\python.exe scripts/rebuild_curated_free_tier.py plan

# Live dev server for E2E verification (with online stores + unrestricted dev/admin providers)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4.2 Code Style & Conventions
- Typed Python 3.12 (`from __future__ import annotations`), explicit error classes (`TavilySearchError`, `DirectLLMError`), `httpx.AsyncClient(verify=system_ssl_context())`, secrets strictly via `app/config.py` (`get_settings()`), zero inline `<script>` or inline `style="..."` in Jinja templates (strict CSP compliance).
```python
class TavilySearchError(RuntimeError):
    def __init__(self, kind: str, *, status_code: int | None = None, latency_ms: float = 0.0) -> None:
        super().__init__(kind)
        self.kind = kind
        self.status_code = status_code
        self.latency_ms = latency_ms
```

### 4.3 Testing Strategy
- **TDD RED → GREEN** on every task: write focused unit/route/JS test first, observe expected failure, implement minimal root-cause code, verify GREEN.
- **Boundary Doubles Only in Unit Tests:** Use `httpx.MockTransport` for Tavily/LLM unit tests; run real live API & browser verification against Qdrant, Supabase, MongoDB, Tavily, and LLM providers in the dedicated live verification phase.

---

## 5. Boundaries

- **Always do:** Preserve CSRF, CSP (`script-src 'self'; style-src 'self'`), owner-scoped Mongo queries, SHA-256 content verification, public user demo quotas (`REVIEWER_DEMO_MODE` for non-admin production users), and honest provenance labels (`corpus` vs `official_external` vs `discovery_hint`).
- **Authorized in this initiative:** Switch/work on `feat/vietlex-v4-fullstack-upgrade`, clean local temp bloat, reclaim wasted Free-Tier Qdrant/Supabase storage and re-index the curated modern normative corpus, read `.env` keys (`TAVILY_API`, AI providers) to run live embedding/RAG/Tavily verification.
- **Ask first before:** Pushing to remote GitHub (`git push`), opening a PR, merging into `main`, promoting a Vercel production alias, or modifying `.env` credentials.
- **Never do:** Log/print API keys or raw `.env` secrets, fabricate benchmark/live test outputs, remove public rate-limits/quotas for unauthenticated internet visitors, or claim unverified web snippets are human-certified consolidated law.

---

## 6. Measurable Success Criteria

1. **Storage & Coverage:** Qdrant Cloud stays `< 2.8 GiB / 4.0 GiB` disk & `< 650 MiB / 1 GiB` RAM; Supabase stays `< 300 MB / 500 MB`; `100%` of articles in `Tier A` (Codes/Laws) and `Tier B` (`2015–2026` Decrees) are searchable online without `16-chunk` loss.
2. **Web & Answer Accuracy:** Tavily Two-Tier supplement resolves post-2024 decrees/circulars (`NĐ 168/2024`, `NĐ 293/2025`, `Luật Đất đai 2024`, `Luật BHXH 2024`, `vbpl.vn` 403 pages) in `< 5s` discovery; live 31-question citizen/legal rubric achieves `>= 90%` (`>= 28/31`) full C1–C6 pass with `0` hallucinated document numbers.
3. **Provider & Server Freedom:** Admin/dev/test mode can freely select and invoke any configured provider (`Vertex`, `Gemini`, `Groq`, `OpenRouter`, `NVIDIA`, `OmniGate`); Semantic Cache records real hits after Input Guardrail; >2 concurrent `/chat` requests no longer trigger `503 demo_capacity_limit`.
4. **UI/UX & Lawyer Tooling:** `/chat` streams tokens live with working Stop button and proper auto-scroll; DOCX upload preserves `<w:numPr>` numbering; Redline produces inline word-level diffs across edited clauses; Full Review auto-runs batches into one Finding Board; DOCX report exports styled Vietnamese OOXML.
5. **Regression Suite:** Full provider-free Python `pytest -m "not live"` and Node `node --test` suites pass with `0` failures.
