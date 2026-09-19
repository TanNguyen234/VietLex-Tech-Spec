# Selected-evidence context budget

Runtime scope: separate selected-source analysis (including comparison, obligations, report, claim verification and model experiments calling its shared prompt) from retrieval chat's 720 approximate whitespace-token budget. Keep retrieval and contract-review batching unchanged. Introduce RESEARCH_CONTEXT_MAX_WORDS=4000 (validated 720..12000), retain the existing 20,000-character and 10-evidence hard limits, count citation/metadata, reject oversized inputs without truncation. Explain these limits in selected-analysis UI and admin configuration. No provider/model, credentials, vector/index, quota or legal-promotion changes.

Failure: three normal selected excerpts of 300 whitespace words each fail before generation despite ten-source selection support. TDD: accept that input under selected budget; still reject word/character/source limits and account for metadata. Real test: same retained public sources/questions, capture requests and provider usage; no claim of complete legal correctness. Full suite after source review; runtime and evidence commits separately; deploy and actual API verification.

Status: scope frozen before implementation. Larger context is not a claim of improved answers; measure it.


Live evidence expanded scope before final verification: aviation status=ok despite no core answer; agriculture inferred a ministry name absent from supplied text; credit claimed missing original sections despite full retained text selected. Freeze three real-output RED gates, clarify selected-answer status and prohibit entity/source-completeness invention, rerun identical evidence. Exact phrase gates are narrow regressions, not a complete legal-correctness score. Any prior full suite/live run predates this prompt change and is not final proof.

Runtime delivered as f4fcb37; production/API/browser verified 2026-09-19. Source-completeness quality gate remains failed; MEDIUM rejected. See [report](../../verification/selected-context-20260919/REPORT.md).
