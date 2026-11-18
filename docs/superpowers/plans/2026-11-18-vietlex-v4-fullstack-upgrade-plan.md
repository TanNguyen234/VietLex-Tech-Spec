# VietLex V4 Full-Stack Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade VietLex end-to-end on branch `feat/vietlex-v4-fullstack-upgrade` — unlocking unrestricted multi-provider routing for dev/test/admin while keeping public user quotas safe, integrating Two-Tier Tavily (`Search` + `Extract`), re-curating Qdrant Cloud & Supabase within Free-Tier limits for 100% modern normative coverage, and delivering real SSE token streaming + reliable lawyer Workspace tools.

**Architecture:** Modular 4-stage pipeline (`mod-1-server-providers` → `mod-2-tavily-web-rag` → `mod-3-corpus-reindex` → `mod-4-ui-lawyer-tools`) built atop the existing FastAPI + Jinja2 SSR + vanilla JS stack. Retrieval and generation are cleanly decoupled; normative laws/decrees (2015–2026) are indexed without 16-chunk truncation in Qdrant/Supabase while Tavily handles real-time discovery/extraction with strict Tier-1/Tier-2 provenance separation.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, `httpx` + `truststore`, `google-genai` (Vertex & Direct), OpenAI-compatible HTTP (`Groq`, `OpenRouter`, `NVIDIA`, `OmniGate`), Tavily REST API, Qdrant Cloud (`1024d` dense + sparse IDF), Supabase PostgreSQL, MongoDB (`motor`), Vanilla JS (strict CSP `script-src 'self'; style-src 'self'`).

## Global Constraints

- Never print, log, or commit raw API keys or secrets from `.env` or `.secrets/`; bind `TAVILY_API` and `TAVILY_API_KEY` via `Settings.tavily_api_key`.
- Keep Qdrant Cloud physical disk `< 2.80 GiB / 4.00 GiB` and RAM `< 650 MiB / 1.00 GiB`; keep Supabase total DB `< 300 MB / 500 MB`.
- Preserve `ReviewerDemoMiddleware` quotas (`20/day` user, `100/day` global, `3/min` user) for unauthenticated/regular non-admin users in `APP_ENV=production`, while allowing unrestricted provider selection & execution in `development`/`test` and for `admin` accounts.
- Maintain strict CSP (`script-src 'self'; style-src 'self'` — zero inline `<script>` or inline `style="..."` attributes in HTML templates) and CSRF verification on all state-mutating routes.
- Follow strict TDD (`RED` → minimal `GREEN` → focused check) per task; run full provider-free suite + live E2E verification before final handoff.

---

## File Structure Map

- **Module 1 (`mod-1-server-providers`):**
  - Modify: `app/config.py`, `app/evaluation/provider_catalog.py`, `app/services/direct_llm.py`, `app/services/serverless_guardrails.py`, `app/services/reviewer_demo.py`, `app/services/semantic_cache.py`, `app/api/routes.py`, `app/main.py`, `app/server.py`, `Dockerfile`
  - Test: `tests/services/test_multi_provider_router.py`, `tests/services/test_reviewer_demo_concurrency.py`, `tests/test_semantic_cache_guardrail_flow.py`
- **Module 2 (`mod-2-tavily-web-rag`):**
  - Create: `app/services/web_source_tiers.py`, `app/services/tavily_search.py`
  - Modify: `app/services/legal_topic_terms.py`, `app/services/official_document_reader.py`, `app/services/trusted_source_reader.py`, `app/services/deep_official_search.py`, `app/services/chat_official_supplement.py`, `app/services/free_web_research.py`, `app/services/deep_research.py`, `app/services/rag_pipeline.py`, `app/services/guardrail_prompts.py`
  - Test: `tests/services/test_web_source_tiers.py`, `tests/services/test_tavily_search.py`, `tests/services/test_reader_and_refusal_fixes.py`
- **Module 3 (`mod-3-corpus-reindex`):**
  - Create: `app/ingestion/curated_normative_corpus.py`, `scripts/rebuild_curated_free_tier.py`
  - Modify: `app/ingestion/legal_text.py`, `app/ingestion/vertex_qdrant_migration.py`, `app/services/vertex_qdrant_retrieval.py`, `app/services/primary_law_rescue.py`
  - Test: `tests/ingestion/test_curated_normative_corpus.py`, `tests/services/test_normative_recency_ranking.py`
- **Module 4 (`mod-4-ui-lawyer-tools`):**
  - Modify: `app/api/routes.py`, `app/api/legal_routes.py`, `app/services/legal_browser.py`, `app/services/document_structure.py`, `app/services/workspace_documents.py`, `app/services/document_redline.py`, `app/services/report_deliverables.py`, `app/templates/index.html`, `app/templates/chat_message.html`, `app/templates/legal_search.html`, `app/templates/legal_document.html`, `app/templates/research_workspace.html`, `app/static/js/vietlex.js`, `app/static/js/research-workspace.js`, `app/static/css/vietlex-redesign.css`
  - Test: `tests/test_chat_streaming_and_ux.py`, `tests/services/test_docx_numbering_and_redline.py`, `tests/services/test_vietnamese_docx_deliverable.py`, `tests/chat_stream_ui.test.cjs`

---

## Module 1 — Server, Multi-Provider Router, Guardrails & Cache (`mod-1-server-providers`)

### Task 1: Config Compatibility (`TAVILY_API` / Provider Defaults), Startup Safety & `ReviewerDemoMiddleware` Concurrency Fix

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/reviewer_demo.py`
- Modify: `app/main.py`
- Modify: `app/server.py`
- Modify: `Dockerfile`
- Test: `tests/services/test_reviewer_demo_concurrency.py`

**Interfaces:**
- Produces:
  - `Settings.tavily_api_key -> Optional[str]` (resolving `TAVILY_API_KEY or TAVILY_API`)
  - `Settings.TAVILY_SEARCH_ENABLED: bool = True`, `Settings.TAVILY_EXTRACT_ENABLED: bool = True`, `Settings.TAVILY_TIMEOUT_SECONDS: float = 8.0`
  - `Settings.DEFAULT_LLM_PROVIDER: str = "auto"`
  - `is_demo_exempt(user: dict | None, settings: Settings) -> bool`

- [ ] **Step 1: Write failing tests for `tavily_api_key`, `active_bodies` body-only scope, and Admin minute-quota exemption**
  ```python
  # tests/services/test_reviewer_demo_concurrency.py
  import asyncio
  import pytest
  from app.config import Settings
  from app.services.reviewer_demo import ReviewerDemoMiddleware, is_demo_daily_exempt

  def test_settings_resolves_tavily_api_alias():
      s = Settings(TAVILY_API="tvly-test-alias", _env_file=None)
      assert s.tavily_api_key == "tvly-test-alias"

  @pytest.mark.anyio
  async def test_active_bodies_released_before_downstream_handler_completes(monkeypatch):
      in_handler = asyncio.Event()
      release_handler = asyncio.Event()

      async def slow_app(scope, receive, send):
          msg = await receive()
          assert msg["type"] == "http.request"
          in_handler.set()
          await release_handler.wait()
          await send({"type": "http.response.start", "status": 200, "headers": []})
          await send({"type": "http.response.body", "body": b"ok"})

      mw = ReviewerDemoMiddleware(slow_app)
      # Verify 3 concurrent slow POST requests do NOT hit 503 demo_capacity_limit once bodies are spooled
  ```
- [ ] **Step 2: Run test to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_reviewer_demo_concurrency.py -q`
  Expected: `FAIL` (`AttributeError: 'Settings' object has no attribute 'tavily_api_key'` and 3rd concurrent request gets `503 demo_capacity_limit`).
- [ ] **Step 3: Implement config properties, body-only `active_bodies` guard, admin minute exemption, and graceful Pinecone/Docker startup**
  - In `app/config.py`: add `TAVILY_API`, `TAVILY_API_KEY`, `TAVILY_SEARCH_ENABLED = True`, `TAVILY_EXTRACT_ENABLED = True`, `TAVILY_TIMEOUT_SECONDS = 8.0`, `DEFAULT_LLM_PROVIDER = "auto"`, and `@property def tavily_api_key(self) -> Optional[str]`.
  - In `app/services/reviewer_demo.py`: decrement `self.active_bodies` inside `finally:` right after buffering `messages` (before `await self.app(scope, replay, send)`), and exempt `is_demo_daily_exempt(user)` (`admin`) from the `3/min` personal AI tuple while preserving all limits for regular users.
  - In `app/main.py`: wrap `ensure_semantic_cache_collection()` so missing Pinecone keys log a warning instead of crashing V3 online startup. Set `SERVERLESS_ONLINE_ONLY=true` default in `Dockerfile` and `app/server.py`.
- [ ] **Step 4: Run focused tests to verify GREEN**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_reviewer_demo_concurrency.py tests/test_config.py -q`
  Expected: `PASS`.

---

### Task 2: Unified Multi-Provider Router, Per-Model Cooldowns, JSON Mode & Streaming Generator

**Files:**
- Modify: `app/evaluation/provider_catalog.py`
- Modify: `app/services/direct_llm.py`
- Modify: `app/services/serverless_guardrails.py`
- Test: `tests/services/test_multi_provider_router.py`

**Interfaces:**
- Produces:
  - `LLMRouteSelection(provider: str = "auto", model: str | None = None)`
  - `list_available_llm_targets(settings: Settings) -> list[dict[str, str]]`
  - `generate_llm_response_with_metadata(..., route: LLMRouteSelection | None = None) -> LLMGenerationResult`
  - `stream_llm_tokens(..., route: LLMRouteSelection | None = None) -> AsyncIterator[str | LLMGenerationResult]`

- [ ] **Step 1: Write failing tests for explicit provider routing, `(provider, model)` cooldown isolation, OmniGate wiring, JSON mode, and guardrail fallback**
  ```python
  # tests/services/test_multi_provider_router.py
  import pytest
  from app.services.direct_llm import LLMRouteSelection, _cooldown_key, _strip_json_fences

  def test_cooldown_is_keyed_by_provider_and_model():
      assert _cooldown_key("gemini", "gemini-2.5-flash") != _cooldown_key("gemini", "gemini-2.5-flash-lite")
      assert _cooldown_key("groq", "qwen/qwen3.8-27b") != _cooldown_key("groq", "openai/gpt-oss-20b")

  def test_strip_json_fences_recovers_fenced_payload():
      raw = "```json\n{\"verdict\": \"supported\"}\n```"
      assert _strip_json_fences(raw) == '{"verdict": "supported"}'
  ```
- [ ] **Step 2: Run test to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_multi_provider_router.py -q`
  Expected: `FAIL` (`ImportError: cannot import name 'LLMRouteSelection'`).
- [ ] **Step 3: Implement multi-provider routing, streaming, JSON mode & guardrail resilience**
  - Key `_cooldowns` by `f"{provider}:{model}"` in `app/services/direct_llm.py` and populate `.observed_model` on `_ProviderText`.
  - Add `omnigate` OpenAI-compatible caller (`OMNIGATE_BASE_URL` + `LITELLM_MASTER_KEY`) and `LLMRouteSelection(provider, model)` so callers can explicitly target `google_vertex_ai`, `gemini`, `groq`, `openrouter`, `nvidia`, or `omnigate` without disabling Qdrant V3 retrieval!
  - Pass `response_format={"type": "json_object"}` / `responseMimeType="application/json"` when `response_mime_type == "application/json"`, plus `_strip_json_fences()` before Pydantic validation.
  - Add `stream_llm_tokens()` supporting Vertex async streaming + SSE streaming for Gemini Direct and OpenAI-compatible providers (`Groq`, `OpenRouter`, `NVIDIA`, `OmniGate`).
  - In `app/services/serverless_guardrails.py`: allow fallback to configured direct providers on transient Vertex `429`/`5xx`, and set reasoning-safe token/thinking parameters so `yes/no` checks never hit `MAX_TOKENS`.
- [ ] **Step 4: Run focused tests (including updated `test_provenance.py`)**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_multi_provider_router.py tests/services/test_serverless_guardrails.py tests/evaluation/test_provenance.py -q`
  Expected: `PASS`.

---

### Task 3: Restore Semantic Cache Behind Mandatory Guardrails & Skip Static Output Guard Calls

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/services/semantic_cache.py`
- Test: `tests/test_semantic_cache_guardrail_flow.py`

**Interfaces:**
- Consumes: `check_input_guardrails`, `check_output_guardrails`, `check_semantic_cache`, `save_to_semantic_cache`
- Produces: Guarded semantic cache flow (`Input Guardrail` → `Semantic Cache Read` → [on miss: `RAG` → `Output Guardrail` → `Semantic Cache Write` if `output_safe`])

- [ ] **Step 1: Write failing test proving `/chat` checks semantic cache AFTER input guardrails and writes ONLY when `output_safe is True`**
- [ ] **Step 2: Run test to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/test_semantic_cache_guardrail_flow.py tests/test_api_routes.py -k "mandatory_guards" -q`
  Expected: `FAIL` (`routes.py:524` skips cache whenever `nemo_enabled` is `True`).
- [ ] **Step 3: Update `app/api/routes.py` cache & static-response guard logic**
  - Allow `check_semantic_cache` after `input_safe` passes (recording `input_executed=True` and binding cached `output_safe=True` provenance), and save to cache only after `output_safe is True`.
  - When `rag_result.observed_provider == "none"` (deterministic clarification or no-evidence static fallback), mark output guardrail `not_needed_static` rather than burning a redundant 75s LLM call.
- [ ] **Step 4: Run focused route & guardrail state tests**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/test_semantic_cache_guardrail_flow.py tests/test_api_routes.py tests/test_guardrail_route_state.py -q`
  Expected: `PASS`.

---

## Module 2 — Two-Tier Tavily Web Search/Extract & RAG Refusal Fixes (`mod-2-tavily-web-rag`)

### Task 4: Fix the 4 Core Web/PDF Reader & Topic Lexicon Bugs

**Files:**
- Create: `app/services/web_source_tiers.py`
- Modify: `app/services/legal_topic_terms.py`
- Modify: `app/services/official_document_reader.py`
- Modify: `app/services/trusted_source_reader.py`
- Modify: `app/services/deep_official_search.py`
- Test: `tests/services/test_web_source_tiers.py`

**Interfaces:**
- Produces:
  - `classify_web_source_tier(url: str) -> Literal["official_primary", "legal_discovery_pivot", "untrusted"]`
  - Accented boundary matching for `"lương"` vs `"khối lượng"` / `"chất lượng"` / `"số lượng"`

- [ ] **Step 1: Write failing tests for `"khối lượng"` false-positive, >40-page PDF inspection validation, `moj.gov.vn` allowlist parity, and final-article retention**
  ```python
  # tests/services/test_web_source_tiers.py
  from app.services.legal_topic_terms import extract_official_topic_phrases
  from app.services.web_source_tiers import classify_web_source_tier

  def test_khoi_luong_does_not_trigger_salary_topic():
      q = "Chủ nguồn thải chất thải nguy hại phải khai báo khối lượng và chất lượng ở đâu?"
      assert "lương" not in extract_official_topic_phrases(q)

  def test_two_tier_domain_classification():
      assert classify_web_source_tier("https://vbpl.moj.gov.vn/vbpq/Lists/Vn%20bn/View_Detail.aspx?ItemID=1") == "official_primary"
      assert classify_web_source_tier("https://quochoi.vn/tintuc/Pages/tin-hoat-dong.aspx") == "official_primary"
      assert classify_web_source_tier("https://thuvienphapluat.vn/van-ban/Giao-thong/Nghi-dinh-168-2024-ND-CP.aspx") == "legal_discovery_pivot"
      assert classify_web_source_tier("https://example.com/blog") == "untrusted"
  ```
- [ ] **Step 2: Run tests to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_web_source_tiers.py tests/services/test_pdf_worker_startup.py -q`
  Expected: `FAIL`.
- [ ] **Step 3: Implement `web_source_tiers.py` and fix reader/lexicon bugs**
  - Create `app/services/web_source_tiers.py` unifying Tier-1 (`*.chinhphu.vn`, `vbpl.vn`, `*.moj.gov.vn`, `*.quochoi.vn`, `*.gov.vn` excluding draft portals) and Tier-2 (`thuvienphapluat.vn`, `luatvietnam.vn`).
  - Fix accented check for `"lương"` in `app/services/legal_topic_terms.py`.
  - Fix `official_document_reader.py:547` (`DEEP_INSPECTION_LIMIT` check), restore `SMART_WORKER_TIMEOUT_SECONDS = 15` (with configurable deep-read override so `test_pdf_worker_startup.py` passes), and support multi-window non-contiguous page selection when multiple `Điều` hints exist!
  - Fix `deep_official_search.py:160` so final articles in a window are kept unless abruptly cut mid-clause.
- [ ] **Step 4: Run focused reader & topic tests**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_web_source_tiers.py tests/services/test_pdf_worker_startup.py tests/services/test_official_document_reader.py tests/services/test_trusted_source_reader.py -q`
  Expected: `PASS`.

---

### Task 5: Implement `TavilyClient` (`Search` + `Extract`) & Two-Tier Discovery-to-Primary Pivot

**Files:**
- Create: `app/services/tavily_search.py`
- Modify: `app/services/deep_official_search.py`
- Modify: `app/services/chat_official_supplement.py`
- Modify: `app/services/free_web_research.py`
- Modify: `app/services/deep_research.py`
- Modify: `app/services/trusted_source_reader.py`
- Test: `tests/services/test_tavily_search.py`

**Interfaces:**
- Produces:
  - `TavilyOfficialClient.search(query: str, *, limit: int = 5, tier: Literal["tier1", "hybrid"] = "hybrid") -> TavilyDiscoveryBundle`
  - `TavilyOfficialClient.extract(urls: Sequence[str], *, query: str | None = None) -> dict[str, ExtractedWebDocument]`
  - `DiscoveryPivotHint(document_numbers: tuple[str, ...], target_articles: tuple[int, ...], superseded_by: dict[str, str])`

- [ ] **Step 1: Write failing unit tests using `httpx.MockTransport` for Tavily Tier-1 search, Tier-2 number/article/validity-hint pivot, and `vbpl.vn` HTTP-403 `extract()` fallback**
- [ ] **Step 2: Run test to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_tavily_search.py -q`
  Expected: `FAIL` (`ModuleNotFoundError: No module named 'app.services.tavily_search'`).
- [ ] **Step 3: Implement `app/services/tavily_search.py` and wire into Chat & Workspace**
  - Call `POST https://api.tavily.com/search` (`include_domains=TIER_1 + TIER_2`, `include_domains_mode="restrict"`, `include_raw_content="markdown"`, `timeout=settings.TAVILY_TIMEOUT_SECONDS`) and `POST https://api.tavily.com/extract`.
  - Extract `DiscoveryPivotHint` from Tier-2 results (`168/2024/NĐ-CP`, `Điều 6`, replacement hints), immediately resolving against local/Supabase corpus first (`<100ms`), then Tier-1 `raw_content` / `CongBaoClient` / `Tavily.extract()`.
  - Remove dead `VbplClient` scraping calls from `deep_official_search.py` (using `Tavily.extract()` when a `vbpl.vn` URL returns `403` in `trusted_source_reader.py`), reducing Chat web supplement P50 latency from `~50s` down to `~2–6s`!
  - Wire `TavilyOfficialClient` into Workspace `free_web_research.py` and `deep_research.py`, and fix `deep_research.build_research_plan` seed extraction.
- [ ] **Step 4: Run focused Tavily & web research tests**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_tavily_search.py tests/services/test_deep_official_search.py tests/services/test_chat_official_supplement.py tests/services/test_free_web_research.py -q`
  Expected: `PASS`.

---

### Task 6: Remove Post-Retrieval Refusal/Context-Wipeout Trap & Harmonize Output Guardrail

**Files:**
- Modify: `app/services/rag_pipeline.py`
- Modify: `app/services/guardrail_prompts.py`
- Modify: `app/services/citation_clause_guard.py`
- Test: `tests/services/test_reader_and_refusal_fixes.py`

**Interfaces:**
- Modifies: `run_advanced_rag` and `generate_response_with_metadata` so valid corpus/Tier-1 contexts are never wiped (`contexts = []`) and current-law/authority questions generate grounded, single-disclaimer answers instead of raw `UNVERIFIED_EFFECT_RESPONSE` blockquotes.

- [ ] **Step 1: Write failing tests for (a) current-authority question with retrieved evidence calling LLM instead of returning `observed_provider="none"`, (b) retaining valid corpus contexts when web supplement times out, and (c) money/percentage/age clause citation verification**
- [ ] **Step 2: Run test to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_reader_and_refusal_fixes.py -q`
  Expected: `FAIL`.
- [ ] **Step 3: Implement grounded conditional generation & expand `citation_clause_guard.py` units**
  - In `app/services/rag_pipeline.py`: preserve valid corpus contexts when web supplement yields 0 new items; replace the LLM-bypassing `_unverified_effect_excerpts` gate when statutory/official contexts exist with grounded LLM generation carrying one concise scope note; query `legal_effect_registry` when MongoDB is available to attach published validity events.
  - Expand `_NUMBER_UNIT` in `app/services/citation_clause_guard.py` to cover `đồng`, `triệu`, `tỷ`, `%`, `phần trăm`, `tuổi`, `điểm` in addition to `ngày/tháng/năm`.
  - Align `OUTPUT_PROMPT` in `app/services/guardrail_prompts.py` so properly attributed answers over `official_external` / corpus provisions pass without false-positive blocks.
- [ ] **Step 4: Run focused RAG & guardrail regression tests**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_reader_and_refusal_fixes.py tests/test_rag_pipeline.py tests/services/test_guardrails.py -q`
  Expected: `PASS`.

---

## Module 3 — Free-Tier Cloud Cleanup & Modern Normative Corpus Re-indexing (`mod-3-corpus-reindex`)

### Task 7: Curated Normative Corpus Selector, Uncapped Structural Chunking & Recency/Validity Ranking

**Files:**
- Create: `app/ingestion/curated_normative_corpus.py`
- Modify: `app/ingestion/legal_text.py`
- Modify: `app/ingestion/vertex_qdrant_migration.py`
- Modify: `app/services/vertex_qdrant_retrieval.py`
- Modify: `app/services/primary_law_rescue.py`
- Test: `tests/ingestion/test_curated_normative_corpus.py`, `tests/services/test_normative_recency_ranking.py`

**Interfaces:**
- Produces:
  - `select_curated_normative_ids(store: ContentStore) -> CuratedCorpusPlan` (`Tier A` `Hiến pháp/Luật/Pháp lệnh` uncapped + `Tier B` `Nghị định 2015–2026` uncapped + `Tier D` `Nghị quyết TW 2015–2026` uncapped + `Tier E` `Thông tư 2020–2026` bounded at `32` chunks, `ORDER BY issuance_date DESC`)
  - Payload fields `issuance_year: int | None`, `normative_rank: int`, `validity_hint: Literal["active_candidate", "superseded"]`

- [ ] **Step 1: Write failing tests verifying `Hiến pháp`, `168/2024/NĐ-CP`, `293/2025/NĐ-CP`, `74/2024/NĐ-CP`, `12/2022/NĐ-CP` are selected, BLDS 2015 retains all `689` articles (`>1,500` chunks, not `16`), `38/2019/QH14` parses articles cleanly, and superseded laws rank below current laws**
- [ ] **Step 2: Run tests to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/ingestion/test_curated_normative_corpus.py tests/services/test_normative_recency_ranking.py -q`
  Expected: `FAIL`.
- [ ] **Step 3: Implement `curated_normative_corpus.py`, fix `ARTICLE_RE`, add per-tier chunk caps (`None` for Laws/Decrees/Central Resolutions), and add validity/normative ranking boost in `vertex_qdrant_retrieval.py`**
  - Also wire Qdrant `vietlex-legal-body-search-v1` exact-phrase lookup as a lightweight fallback inside `rag_pipeline.py` so `primary_law_rescue.py` no longer relies on brittle 1,100-line keyword whack-a-mole.
- [ ] **Step 4: Run focused ingestion & retrieval tests**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/ingestion/test_curated_normative_corpus.py tests/services/test_normative_recency_ranking.py tests/services/test_primary_law_rescue.py -q`
  Expected: `PASS`.

---

### Task 8: Execute Checkpointed Free-Tier Cloud Reclamation & Curated Re-Index (`Qdrant` + `Supabase`)

**Files:**
- Create: `scripts/rebuild_curated_free_tier.py`
- Test: `tests/scripts/test_rebuild_curated_free_tier.py`

**Interfaces:**
- CLI subcommands: `plan` (provider-free byte & point audit), `reclaim` (drops dead Supabase `legal_body_passages` + unused GIN shards & dormant Qdrant `v2-pilot` / `rerank-staging` after writing pre-state receipt), `sync` (reuses existing `inference_text_sha256` vectors from V3, batch-embeds new chunks via Vertex `gemini-embedding-2` `1024d`, syncs Qdrant V3 + Qdrant body-search + Supabase `public.legal_documents`), `verify` (cryptographic count, SHA-256 parity, disk/RAM/MB quota check).

- [ ] **Step 1: Write unit tests for `plan` and vector-reuse diffing logic**
- [ ] **Step 2: Run unit test to verify RED → implement `scripts/rebuild_curated_free_tier.py` → verify GREEN**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/scripts/test_rebuild_curated_free_tier.py -q`
- [ ] **Step 3: Run `plan`, `reclaim`, `sync`, and `verify` against live Free-Tier Qdrant & Supabase, saving immutable receipts**
  Run:
  ```powershell
  .\.venv\Scripts\python.exe scripts/rebuild_curated_free_tier.py plan
  .\.venv\Scripts\python.exe scripts/rebuild_curated_free_tier.py reclaim --confirm-free-tier-cleanup
  .\.venv\Scripts\python.exe scripts/rebuild_curated_free_tier.py sync
  .\.venv\Scripts\python.exe scripts/rebuild_curated_free_tier.py verify
  ```
  Expected: `verify` exits `0` with 1:1 ID parity across Qdrant V3, Qdrant Body Search, and Supabase `legal_documents`; Qdrant disk `< 2.8 GiB`, Supabase total DB `< 300 MB`, and `689/689` BLDS + `220/220` BLLĐ + `55/55` NĐ 168/2024 articles verified live.

---

## Module 4 — Dual-Persona UI/UX & Lawyer Workspace End-to-End Upgrade (`mod-4-ui-lawyer-tools`)

### Task 9: Real SSE Token Streaming (`POST /chat/stream`), Cancel Button, Scroll Fix & Clean Dual-Persona Chat UI

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/templates/index.html`
- Modify: `app/templates/chat_message.html`
- Modify: `app/static/js/vietlex.js`
- Modify: `app/static/css/vietlex-redesign.css`
- Test: `tests/test_chat_streaming_and_ux.py`, `tests/chat_stream_ui.test.cjs`

**Interfaces:**
- Produces: `POST /chat/stream` (`application/x-ndjson` stream emitting `{"type":"stage","label":...}`, `{"type":"delta","text":...}`, `{"type":"complete","html":...,"session_id":...,"title":...}`, `{"type":"error","status":...,"message":...,"login_url":...}`).

- [ ] **Step 1: Write failing Python route + Node JS tests for `POST /chat/stream`, `AbortController` cancel button, `+ Mới` first-message auto-titling, actionable `401`/`503` error banners, sticky scroll layout, and Admin/Dev model + web-mode picker**
- [ ] **Step 2: Run tests to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/test_chat_streaming_and_ux.py -q` and `node --test tests/chat_stream_ui.test.cjs`
- [ ] **Step 3: Implement `POST /chat/stream`, real token streaming in `vietlex.js` (removing the fake typewriter loop), Stop button, suggested legal prompt chips, collapsible technical telemetry, single consolidated provenance footer, and CSS viewport scroll fix**
- [ ] **Step 4: Run Python & Node UI tests to verify GREEN**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/test_chat_streaming_and_ux.py tests/test_public_templates.py tests/test_chat_recovery_accessibility.py -q` and `node --test tests/*.test.cjs`
  Expected: `PASS`.

---

### Task 10: Upgrade `/search` Filters/Pagination & Hierarchical `/documents/{id}` Statute Reader

**Files:**
- Modify: `app/services/legal_browser.py`
- Modify: `app/api/legal_routes.py`
- Modify: `app/services/document_structure.py`
- Modify: `app/templates/legal_search.html`
- Modify: `app/templates/legal_document.html`
- Modify: `app/static/js/legal-search.js`
- Test: `tests/services/test_vietlex_feature_pack.py`, `tests/test_legal_routes.py`

- [ ] **Step 1: Write failing tests for case-insensitive `legal_type`/`authority` filter dropdowns, pre-pagination `sector` filtering, `Phần/Chương/Mục/Điều/Phụ lục` parsing, and >4,000-char clause-window pinning**
- [ ] **Step 2: Run tests to verify RED failure**
- [ ] **Step 3: Implement SQL/PostgREST pre-pagination `sector` & `ilike` filters, `<select>`/`<datalist>` filter controls, optional `as_of` UX clarity, hierarchical statute reader with instant TOC filter, and sliding-window section pinning**
- [ ] **Step 4: Run focused search & reader tests to verify GREEN**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_vietlex_feature_pack.py tests/services/test_legal_browser.py tests/test_legal_routes.py -q`
  Expected: `PASS`.

---

### Task 11: Lawyer Workspace Upgrade — DOCX Auto-Numbering/Tables, Inline Word-Level Redline, Auto-Batch Review & Vietnamese DOCX Export

**Files:**
- Modify: `app/services/workspace_documents.py`
- Modify: `app/services/document_redline.py`
- Modify: `app/services/report_deliverables.py`
- Modify: `app/templates/research_workspace.html`
- Modify: `app/templates/admin_legal_registry.html`
- Modify: `app/static/js/research-workspace.js`
- Test: `tests/services/test_docx_numbering_and_redline.py`, `tests/services/test_vietnamese_docx_deliverable.py`

- [ ] **Step 1: Write failing tests for (a) Word `numbering.xml` `<w:numPr>` + `<w:tbl>` extraction, (b) Redline matching edited clauses across two distinct contract files with inline word `<del>`/`<ins>` tokens, and (c) Vietnamese OOXML DOCX report export containing `word/styles.xml` and Vietnamese headings**
- [ ] **Step 2: Run tests to verify RED failure**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_docx_numbering_and_redline.py tests/services/test_vietnamese_docx_deliverable.py -q`
- [ ] **Step 3: Implement Workspace upgrades**
  - Parse `word/numbering.xml` + `<w:tbl>` markdown tables in `workspace_documents.py`.
  - Replace dead `clause_id` Pass-2 in `document_redline.py` with structural-number + title/Jaccard similarity pairing and word-level inline diff tokens.
  - Build complete OOXML (`word/styles.xml`, A4 margins, Vietnamese legal typography & headings) in `report_deliverables.py`.
  - Keep a persistent collapsible Evidence Selection drawer visible across `#analysis`, `#review`, and `#reports` in `research_workspace.html`; add `"Chạy tự động toàn bộ các lô"` + unified Finding Board aggregation in `research-workspace.js`; list all pending workspace reviews on `/admin/legal-registry` even without `?workspace_id`.
- [ ] **Step 4: Run Workspace & deliverable test suites to verify GREEN**
  Run: `.\.venv\Scripts\python.exe -B -m pytest tests/services/test_docx_numbering_and_redline.py tests/services/test_vietnamese_docx_deliverable.py tests/test_report_deliverables.py tests/test_document_redline_routes.py tests/test_workspace_routes.py -q`
  Expected: `PASS`.

---

### Task 12: Full Regression Gate, Live 31-Question Legal Rubric & End-to-End Lawyer Verification

**Files:**
- Modify: `FEATURE_STATUS.md`, `docs/CURRENT_ARCHITECTURE.md`, `docs/PROJECT_CONTEXT.md`
- Create: `docs/evaluation/runs/v4-fullstack-upgrade-20261118/REPORT.md`

- [ ] **Step 1: Run `ruff` lint, Node JS suite, and full provider-free Python test suite**
  Run:
  ```powershell
  .\.venv\Scripts\python.exe -m ruff check app tests scripts
  node --test tests/*.test.cjs
  .\.venv\Scripts\python.exe -B -m pytest tests -q -m "not live"
  ```
  Expected: `0` lint errors, `100%` Node pass, `0` Python failures.
- [ ] **Step 2: Run live end-to-end verification against local uvicorn + live Qdrant/Supabase/MongoDB/Tavily/AI Providers**
  - Execute the 31-question natural Vietnamese legal Q&A rubric (verifying C1–C6 citations, streaming TTFT, Tavily Tier-1/Tier-2 discovery, and zero hallucinated statutes).
  - Exercise Lawyer Workspace flows end-to-end (Tavily official research stream, DOCX upload with auto-numbering, inline word Redline, auto-batch Contract Review, and styled Vietnamese DOCX download) + verify public non-admin demo quota enforcement remains intact.
- [ ] **Step 3: Record immutable run manifest & update `docs/CURRENT_ARCHITECTURE.md`, `docs/PROJECT_CONTEXT.md`, and `FEATURE_STATUS.md`**
