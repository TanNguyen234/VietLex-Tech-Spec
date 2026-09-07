# Admin token breakdown

Runtime presentation/accounting change. Scope: admin_observability.py, admin_quality.html, focused tests. Reuse the stored call ledger and existing aggregation. Per-group counts cover retained calls only; dropped calls cannot be assigned to a provider/model and must be disclosed globally. Validate nonnegative bounded integer token values consistently with request summaries; expose input/output/thinking/total with independent coverage, missing values as N/A and measured zero as zero. No pricing guesses, providers, migration or raw-content logging.

RED: render a partial group with zero input, absent output, thinking and a dropped-call warning. Verify aggregation uses the same integer guard as request accounting. GREEN then independent review, full provider-free suite once with process-local Git safe.directory and fresh basetemp. Artifacts after stable source; commit/push authorized.
