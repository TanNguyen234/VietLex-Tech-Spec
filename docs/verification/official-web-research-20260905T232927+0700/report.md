# Official web research verification

- Verified at: 2026-09-05T23:29:27+07:00
- Base commit: `2bca7f990ae22bffdc4e25497fee7e5ecc6c445a`
- Branch: `main`
- Classification: runtime/product workflow
- Provider impact: read-only requests to the public Government document portal; no LLM, embedding, reranker, ingestion, vector write, or paid-provider call

## Verified contract

- Plan creation is deterministic and provider-free. A user reviews and may edit exactly five bounded queries before running them.
- Execution reads `https://vanban.chinhphu.vn/he-thong-van-ban`, rejects redirects before forwarding Web Forms state, streams each response under a 2 MB cap, and fails explicitly when the expected form or result-table contract is absent.
- Only HTTPS result URLs on the exact government-domain allowlist are retained. The UI and persisted record describe these as result metadata, not grounded legal conclusions or verified legal-effect status.
- External HTTP telemetry retains protocol, outcome, latency and request count separately from LLM calls and token usage. A failed workspace save corrects the request trace to `workspace_changed`.
- Workspace routes preserve existing owner scoping, CSRF validation and a dedicated `2/minute` rate limit.

## Verification evidence

Focused tests:

```text
.venv\Scripts\python.exe -m pytest -q tests/services/test_official_web_search.py tests/services/test_deep_research.py tests/services/test_admin_observability.py tests/test_workspace_routes.py tests/test_public_templates.py
51 passed, 5 warnings in 3.49s
```

Independent stable-diff review:

```text
No P1/P2 findings after fixes.
Focused reviewer suite: 51 passed.
```

Full provider-free test suite:

```text
.venv\Scripts\python.exe -m pytest -q
1047 passed, 2 skipped, 16 warnings in 199.97s
```

Static gates:

```text
.venv\Scripts\python.exe -m ruff check app tests
All checks passed!

node --check app/static/js/research-workspace.js
exit 0

git diff --check
exit 0 (line-ending notices only)
```

Read-only live portal sample:

```text
Question: Điều kiện đơn phương chấm dứt hợp đồng lao động
Overall: partial
legal_basis: results_found (3)
conditions: no_results (0)
exceptions: results_found (1)
amendments: no_results (0)
official_verification: results_found (3)
Provider: chinhphu_official_portal / webforms-search-v1
```

The sample proves the live form contract and explicit partial-result behavior at that time. It does not prove legal correctness, corpus completeness, or current legal effect.

UI inspection used the local preview fixture at `C:\Users\VI TINH THANH AN\.codex\visualizations\2026\09\05\01a071a4-6fcb-7d02-9030-6250073c3697\deep_research_preview.py`. The workspace rendered without horizontal overflow at 1280 px and 390 px widths; plan creation and editable query fields were exercised. The preview server was stopped after inspection.

## Known limits

- This slice discovers bounded metadata from one official portal. It does not fetch and interpret article text, determine amendment chains, or certify validity.
- `no_results` means that the portal returned no parsed rows for that query; it does not prove that no applicable instrument exists.
- The concurrency semaphore is process-local. Multi-replica global throttling is not implemented.
- Existing deprecation warnings concern Starlette/httpx test compatibility and naive `datetime.utcnow()` usage; no test failed.

## Git state boundary

The commit for this feature must exclude inherited user work: `.codex/config.toml` and the four untracked `docs/evaluation/runs/retrieval-v3-*` directories present before this change.
