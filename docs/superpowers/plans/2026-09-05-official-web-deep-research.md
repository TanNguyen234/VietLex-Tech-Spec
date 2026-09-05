# Official web and deep research implementation plan

## Frozen contract

- Classification: runtime/product workflow.
- Authority: current source/tests and `app/config.py`; official source discovery augments the pinned retrieval contracts and never silently replaces them.
- User flow: create a deterministic, editable research plan; a separate explicit action runs it.
- Provider boundary: direct read-only search against the Government document portal when enabled; plan creation remains provider-free and the workflow makes no LLM/token call.
- Evidence boundary: retain only exact allowlisted government hosts and bounded official result metadata. Google Search Grounding is excluded because its production display/storage terms conflict with persisted workspaces.
- Failure state: disabled, provider error, no official source, and partial completion remain distinct and observable.
- Persistence: save the bounded plan, per-step query/status/source metadata in the owner-scoped workspace; record external HTTP telemetry separately from LLM/token usage.
- Limits: 5 steps, 10 sources per step, bounded question/query/text, existing CSRF/rate limits, no background or full-corpus mutation.

## Focused RED

- [x] Government Web Forms adapter preserves state, parses bounded results, and fails explicitly on contract/size errors.
- [x] Official-domain validation rejects suffix-spoofed hosts and non-HTTPS links.
- [x] Research execution suppresses non-official results and reports partial result coverage.
- [x] Routes preserve ownership, CSRF, enablement, plan validation, persistence and request telemetry.
- [x] Workspace renders plan approval, progress/result semantics, and saved official-source dossiers.

## Stable verification

- [x] Focused service/route/template/config tests: 51 passed.
- [x] Stable-diff review and security/error-path review: no P1/P2 findings.
- [x] Ruff and full provider-free suite once: 1047 passed, 2 skipped.
- [x] Durable verification report after source/config stabilization.
