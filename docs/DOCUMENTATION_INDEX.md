> Update 2026-11-03: Ragas completed on all 50 saved answers (faithfulness 0.8333; accuracy 0.9000; context precision 0.8708; recall 0.9490; zero technical errors). L04 has an AI source review, not independent human legal approval. General production readiness remains unproven. See [release verification](tasks/production-readiness-20261103/REPORT.md).

# VietLex documentation index

Updated: 2026-10-19.

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
| System handbook | [`handbook/index.md`](handbook/index.md) | Ten chapters on data, ingestion, retrieval, providers, stores, backend, frontend, roles, operations, and trade-offs |
| 2026-10-18 verification update | [`verification/system-handbook-free-web-20261017/REPORT.md`](verification/system-handbook-free-web-20261017/REPORT.md) | Bounded capacity/source provenance, official-source live probe, corrected reader comparison, fresh provider-free suite result, and remaining limits |
| 2026-10-18 production release | [`verification/production-release-20261018-01/REPORT.md`](verification/production-release-20261018-01/REPORT.md) | Deployment identity, readiness, bounded role checks, actual browser answer, and pending release probes |
| Feature status | [`../FEATURE_STATUS.md`](../FEATURE_STATUS.md) | Current bounded evidence snapshot followed by dated feature history |
| Evaluation status | [`evaluation/CURRENT_STATUS.md`](evaluation/CURRENT_STATUS.md) | Latest bounded benchmark and retained historical status log |
| Portfolio claims | [`evaluation/PORTFOLIO_EVIDENCE.md`](evaluation/PORTFOLIO_EVIDENCE.md) | Claims allowed by immutable evidence and their boundaries |
| Vercel deployment | [`runbooks/DEPLOYMENT.md`](runbooks/DEPLOYMENT.md) | Direct FastAPI/Jinja SSR deployment contract |
| Persistent operations | [`PRODUCTION_OPERATIONS.md`](PRODUCTION_OPERATIONS.md) | Backups, restores, monitoring, account/admin bootstrap, and persistent-host responsibilities |
| Corpus ingestion | [`huggingface-ingestion-runbook.md`](huggingface-ingestion-runbook.md) | Full-corpus preparation and verification |
| Golden-50 | [`evaluation/golden50-v3/README.md`](evaluation/golden50-v3/README.md) | Reproducible online retrieval and answer evaluation commands |
| Legal Intelligence Workspace | [`superpowers/plans/2026-09-04-legal-intelligence-workspace.md`](superpowers/plans/2026-09-04-legal-intelligence-workspace.md) | Current additive workspace, evidence, structured-analysis, retrieval-inspector, and Evaluation Lab contract |

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

The [18 October production release](verification/production-release-20261018-01/REPORT.md) records 90/90 role checks, two durably saved/replayed web sources, and three natural-language chat submissions without a full legal-quality pass. Disconnect cancellation stayed UNKNOWN during a ten-second observation. The [19 October cancellation follow-up](verification/production-release-20261018-01/cancel-fix-20261019-01/REPORT.md) separately binds its source, suite, deployment and live checks. The old 1,704-test receipt belongs to the pre-cancellation snapshot; later evidence cannot be inferred from it. Qdrant V3/Supabase cover 14,962 online IDs; capacity expansion remains BLOCKED. Deployment readiness does not establish legal-answer quality.

The latest retained Golden-50 answer evidence is dated 2026-09-03. The RRF+DBSF retrieval run
passed its bounded quality gate, but deterministic answer exact match remained
`0.0000` and token F1 was `0.2305`; optional Ragas covered 50/50 while observed
faithfulness fell from `0.8887` to `0.8221` versus the prior run.
Therefore neither deployment success nor opt-in Ragas scores
authorize a production-readiness or whole-corpus legal-accuracy claim.

The 19 October cancellation source passed 1,715 provider-free tests (1 skipped, 6 deselected); its deployment/live identity is recorded only in the linked follow-up report.
