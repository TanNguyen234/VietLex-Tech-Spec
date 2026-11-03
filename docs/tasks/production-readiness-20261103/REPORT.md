# Release verification — 2026-11-03

## Decision and authority

Technical acceptance is supported within the recorded scope. General production readiness is not demonstrated. The user authorized commits, push to main, the Ragas audit and an AI review of L04. AI source review does not establish independent human legal approval.

## Verification results

| Evidence | Result | Level / limitation |
| --- | --- | --- |
| Python full suite | 2240 passed, 6 live deselected | Provider-free; full27, 417.27 seconds |
| Node suite | 22 passed | Frontend/session tests |
| Frozen HTTP cases | 8/8 executed | Live deployment; ADMIN/USER ownership checks passed |
| Golden50 | 50 completed, no technical errors | Real Vertex/Qdrant service; distinct from HTTP load testing |
| Input/output guardrails | 50/50 each | Mandatory public enforcement; 20-second timeout |
| Document/article/clause Recall@3 | 53/53; 29/30; 13/14 | Label coverage limited; see full metric denominators |
| Multi-hop full coverage | 38/40 | Existing retrieval gate passed |
| Citation precision / invalid rate | 0.9679 / 0.0321 | Offline metric 3.3 on saved answers |
| Ragas faithfulness | 40.83015873015873 / 49 = 0.8332685455 | Coverage 49/50; one no_prompt_contexts skip |
| Ragas answer accuracy | 45 / 50 = 0.9000 | Coverage 50/50 |
| Ragas context precision | 42.67063491711241 / 49 = 0.8708292840 | Coverage 49/50 |
| Ragas context recall | 46.5 / 49 = 0.9489795918 | Coverage 49/50 |
| Ragas errors | 0 | 754 successful structured judge calls |
| Service latency P50 / P95 | 56.9511 / 62.6539 seconds | No isolated HTTP load test |

Ragas used the same saved 50 answers and prompt contexts as deterministic scoring. It did not regenerate answers or change the database. The requested judge was gemini-3.5-flash, from the same model family as generation. Token usage, transport retry count and returned model version are UNKNOWN. These 754 logical calls are not a billing statement. There are 17/49 faithfulness scores below 0.8. Scores are secondary model judgments, not proof of legal correctness. The one-case preflight is preserved separately and is not blended into this audit.

Number/date/entity gold is absent; citation-recall gold exists for only one case. All 50 cases are answerable, so refusal recall is not established. These gaps, latency and incomplete legal-currentness evidence prevent an unrestricted production-ready declaration.

## L04

[AI source review](../../legal/L04-AI-SOURCE-REVIEW-20261103.md) records the qualified legal-source conclusion and official references. No human signature, legal registry approval or gold-label promotion was fabricated. Independent human approval and exhaustive current-law inventory remain unestablished. Runtime retains its legal-currentness deferral.

## Reproducible evidence

- [Full deterministic metrics](../../evaluation/runs/crg-golden50-20261103-3ee9f610/FULL_METRICS.md)
- [Technical acceptance report and commands](../../evaluation/runs/crg-golden50-20261103-3ee9f610/REPORT.md)
- [Ragas manifest](../../evaluation/runs/ragas-golden50-20261103-256a0838/manifest.json)
- [Ragas report](../../evaluation/runs/ragas-golden50-20261103-256a0838/REPORT.md)
- [Ragas raw results](../../evaluation/runs/ragas-golden50-20261103-256a0838/results.json)
- [Ragas call ledger](../../evaluation/runs/ragas-golden50-20261103-256a0838/judge-call-ledger.json)

All 447 runtime/source/config/test file hashes remained unchanged after full27 verification and the Ragas audit. No runtime change was made while preparing this release documentation. Earlier failed baselines remain published. Manifests retain dirty-tree proof; a later commit does not retroactively make those runs clean-tree runs. Three inaccessible temporary directories prevent claiming an exhaustive untracked inventory.

## Delivery and boundaries

Runtime and tests are in commit 79fcff9; mandatory policy and offline CRG configuration are in 807f513. Evaluation evidence and documentation are separate commits. Selected immutable evidence was staged with git -c core.autocrlf=false add and every staged blob checked against its worktree SHA-256: 543 files, zero mismatches, zero configured-secret matches. Runtime staging retained normal repository EOL behavior. Seven pre-existing extra EOF blank-line warnings were recorded; the whitespace check excluding blank-at-eof passed.

No ingestion, persistent migration, collection deletion, credential edit, quota bypass or force push was performed. Unrelated writing-plans skill deletions and unrelated historical untracked files are excluded. Exact delivery commit IDs and remote verification are reported after the normal push; this report does not assume push success.
