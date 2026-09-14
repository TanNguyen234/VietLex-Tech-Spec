# Source temporal context

Runtime scope: preserve source-reported effective dates and provenance in selected-evidence and contract-review prompts. No legal-status promotion, corpus mutation, model/provider change, or silent scope expansion.

Observed failure: metadata is persisted by trusted_source_routes but omitted by research_analysis prompt builders. Real aviation baseline returns insufficient_evidence and says the date is missing, although the selected record contains reported_effective_from=01-01-2027. This is unnecessary information loss, not an observed hallucinated current-law claim. Original PDF page 4 confirms that date; global legal validity remains unverified.

Contract: forward only explicit provenance fields as untrusted data, preserve existing context budgets, distinguish source-reported dates from verified current status, require time-qualified analysis when a question supplies a date. Review scope includes selected answers, comparisons, obligation matrices, reports and contract review. Failure checks: metadata missing, irrelevant/private fields leaked, context budget silently expanded.

Sequence: pure RED tests; shared metadata formatter and both prompt builders; focused tests; identical-input live before/after comparison; stable diff review; broader suite once; then commit, push, deploy and publish evidence.
