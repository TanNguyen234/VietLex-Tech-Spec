# VietLex

VietLex is an evidence-oriented Vietnamese legal research application. It supports document retrieval, official-source reading, preserved excerpts, owner-scoped conversations and research exports.

[Application](https://vietlex-legal-rag.vercel.app) · [Tiếng Việt](README.md) · [Release assessment](docs/tasks/production-readiness-20261103/REPORT.md)

## Release status

The 3 November 2026 deployment has passed automated checks and bounded live HTTP acceptance. **General production readiness is not demonstrated.** Golden50 is a narrow evaluation set, the Ragas judge uses the same model family as generation, and L04 has an AI source review rather than independent legal approval.

## Measured results

Golden50 used the production service with real Vertex/Qdrant providers. Deterministic metric 3.3 and Ragas evaluated the same saved 50 responses and prompt contexts. The eight production-domain HTTP cases are separate evidence.

| Check | Result | Coverage |
| --- | ---: | --- |
| Python / Node | 2,240 / 22 passed | Six live tests deselected from the provider-free suite |
| Frozen HTTP / roles | 8/8; ADMIN/USER passed | Guardrails, persistence, replay/export and PDFs |
| Input / output guardrails | 50/50 each | Mandatory enforcement |
| Document / article / clause Recall@3 | 53/53; 29/30; 13/14 | 40 verified cases; 10 without retrieval gold skipped |
| Multi-hop full coverage | 38/40 | Existing retrieval gate passed |
| Exact match / token F1 | 0.0000 / 0.2323 | 50 cases; not a legal correctness verdict |
| Citation precision / invalid rate | 0.9679 / 0.0321 | Metric 3.3; 49 applicable cases |
| Ragas faithfulness | 0.8333 | 49/50; one case has no prompt contexts |
| Ragas answer accuracy | 0.9000 | 50/50 |
| Ragas context precision / recall | 0.8708 / 0.9490 | 49/50 |
| Ragas technical errors | 0 | 754 recorded structured judge calls |
| End-to-end P50 / P95 | 56.95 / 62.65 seconds | Service benchmark, not an HTTP load test |

Seventeen of 49 cases have judge faithfulness below 0.8. Number/date/entity gold labels are absent, so those deterministic metrics are N/A. Reference-citation recall has gold for only one of 50 cases. Missing coverage is not treated as a pass.

See the [full deterministic metrics](docs/evaluation/runs/crg-golden50-20261103-3ee9f610/FULL_METRICS.md), [Ragas summary](docs/evaluation/runs/ragas-golden50-20261103-256a0838/summary.json), [per-case scores](docs/evaluation/runs/ragas-golden50-20261103-256a0838/results.json) and [verification record](docs/evaluation/runs/crg-golden50-20261103-3ee9f610/REPORT.md).

## Data and architecture

The pinned third-party [dataset](https://huggingface.co/datasets/vohuutridung/vietnamese-legal-documents) contains 518,255 records at revision `4d4e10b201544e8a4c49a1d3fa496595a7d486d0`. This is not the online index count. The dated 27 October audit records 14,982 document IDs and 142,063 Qdrant V3 points; this release did not repeat a complete remote corpus audit.

| Runtime selection | Contract |
| --- | --- |
| `USE_LEGACY_FREE_PIPELINE=false` | Vertex `gemini-embedding-2`, 1024 dimensions, Qdrant V3, sparse IDF and RRF+DBSF blend |
| `USE_LEGACY_FREE_PIPELINE=true` | E5-small, 384 dimensions, Pinecone V1 and SQLite/Zstandard; Google/Vertex blocked before client creation |
| Web application | FastAPI, Jinja/HTMX and owner-scoped research state |
| External official sources | Request-scoped URL/hash/page evidence; no automatic legal verification |

The two retrieval contracts do not silently cross-fallback. Public chat guardrails enforce in local and online environments; legacy client off/shadow/false values cannot disable them. The default decision timeout is 20 seconds. Technical failures remain typed errors, separate from semantic rejection.

## L04 source review

The [L04 AI source review](docs/legal/L04-AI-SOURCE-REVIEW-20261103.md) distinguishes permit obligations, authority, 2025–2026 amendments and transition rules for the frozen 29 October question. Its qualified source conclusion does not establish a general no-emissions exemption for imported scrap.

This is an AI review requested by the user, not an invented expert signature. No gold labels or human-approved registry records were changed. Complete currentness certification remains unestablished; runtime withholds that conclusion when the evidence chain is incomplete.

## Local development

Python 3.12 is required. These steps do not download the corpus or create/migrate indexes:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-demo.lock
python -m pip install . --no-deps
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. Full chat requires the selected providers and data sources; a working UI does not prove dependency readiness. Never commit credentials, `.env` or local corpus stores.

```powershell
python -m pytest -m "not live" -q
node --test tests/*.test.cjs
```

Default deterministic evaluation makes no Ragas calls. Live evaluation requires explicit invocation and may incur provider charges. The [Vietnamese README](README.md#kiểm-thử-và-đánh-giá) includes the production-service command. The [Ragas manifest](docs/evaluation/runs/ragas-golden50-20261103-256a0838/manifest.json) records its separate saved-answer audit, source/input hashes and library versions. The requested judge model is `gemini-3.5-flash`; token usage and returned model version are UNKNOWN at the current adapter boundary.

Review original official sources and applicability dates before relying on an answer. VietLex is not an official legal database or a substitute for professional legal advice. Full ingestion, persistent vector migrations and index deletion/rebuild require separate authorization.
