# VietLex documentation index

Updated: 2026-09-03.

This page routes readers to the correct source. A filename containing
`architecture`, `plan`, `report`, or `current` does not by itself make that
file authoritative.

## Authority order

1. Current code and tests.
2. [`app/config.py`](../app/config.py).
3. [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md).
4. [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md).
5. Current runbooks.
6. Dated reports, specifications, plans, and retained historical artifacts.

When two documents conflict, use this order and report the conflict instead of
reviving an older design.

## Current documents

| Area | Current document | Purpose |
| :--- | :--- | :--- |
| Project entry | [`README.md`](../README.md), [`README.en.md`](../README.en.md) | Supported runtime contracts, setup, evidence, and limitations |
| Agent rules | [`AGENTS.md`](../AGENTS.md), [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md) | Authority, safety, evaluation, and verification workflow |
| Project context | [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Pinned corpus, stores, providers, and evaluation policy |
| Architecture | [`CURRENT_ARCHITECTURE.md`](CURRENT_ARCHITECTURE.md) | Technical source of truth for current code |
| Evaluation status | [`evaluation/CURRENT_STATUS.md`](evaluation/CURRENT_STATUS.md) | Latest bounded benchmark and retained historical status log |
| Portfolio claims | [`evaluation/PORTFOLIO_EVIDENCE.md`](evaluation/PORTFOLIO_EVIDENCE.md) | Claims allowed by immutable evidence and their boundaries |
| Vercel deployment | [`runbooks/DEPLOYMENT.md`](runbooks/DEPLOYMENT.md) | Direct FastAPI/Jinja SSR deployment contract |
| Persistent operations | [`PRODUCTION_OPERATIONS.md`](PRODUCTION_OPERATIONS.md) | Backups, restores, monitoring, and persistent-host responsibilities |
| Corpus ingestion | [`huggingface-ingestion-runbook.md`](huggingface-ingestion-runbook.md) | Full-corpus preparation and verification |
| Golden-50 | [`evaluation/golden50-v3/README.md`](evaluation/golden50-v3/README.md) | Reproducible online retrieval and answer evaluation commands |

## Evidence-bearing history

- `docs/evaluation/runs/<run-id>/` directories are immutable run evidence.
- `docs/evaluation/comparisons/`, `index-pilots/`, `adjudication/`, and dated
  evaluation reports preserve the contract and outcome that existed when they
  were written. They do not automatically describe the current runtime.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` are design and
  execution history. Current code/tests decide whether a proposal shipped.

Do not edit an old run to make it agree with a newer architecture. Create a new
run or update a current status document that links to both artifacts.

## Explicitly historical compatibility files

- [`../plan.md`](../plan.md): July-era Cohere/OmniGate technical specification.
- [`../nemo_guardrails_features.md`](../nemo_guardrails_features.md): early
  NeMo feature analysis, not the current guardrail contract.
- [`../architecture/architecture.md`](../architecture/architecture.md): legacy
  path retained for links; it redirects to the canonical architecture.
- [`ux_ui_evaluation_report.md`](ux_ui_evaluation_report.md): dated UX audit
  from before the current session, evidence drawer, and production SSR work.
- `system_evaluation_report.md`, `smoke_evaluation_report.md`, and
  `fix_smoke_evaluation_report.md`: dated August 2026 snapshots.

## Current deployment and evidence boundary

The active public deployment is direct Vercel FastAPI/Jinja SSR at
<https://vietlex-legal-rag.vercel.app>. It uses the audited online Qdrant v3
slice of 141,798 points over exactly 14,962 document IDs. Supabase exposes the
same 14,962 full documents for online title/number search and document pages.
That is not the pinned
518,255-document corpus. The full-corpus Pinecone v1 path remains the explicit
legacy/free runtime selected by `USE_LEGACY_FREE_PIPELINE=true`.

The latest Golden-50 evidence is dated 2026-09-03. The RRF+DBSF retrieval run
passed its bounded quality gate, but deterministic answer exact match remained
`0.0000` and token F1 was `0.2305`; optional Ragas covered 50/50 while observed
faithfulness fell from `0.8887` to `0.8221` versus the prior run.
Therefore neither deployment success nor opt-in Ragas scores
authorize a production-readiness or whole-corpus legal-accuracy claim.
