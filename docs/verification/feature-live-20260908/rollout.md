# Final runtime rollout evidence — 2026-09-08

This addendum resolves the creation-time pending state in the original manifest.
Runtime fix: `8cbd948147b0bf1fdd3cfefc7a92032f0b202cb5`.
Deployed package: `da058102541598c1609231a4279cf64a9ca4ba7d`.

- [CI 34254476509](https://github.com/TanNguyen234/VietLex-Tech-Spec/actions/runs/34254476509): test-and-lint and Docker build-and-push **SUCCESS**.
- [Vercel deployment](https://vercel.com/foxys-projects-5fe642e0/vietlex-legal-rag/EKzyyfQYTmbduxGqdUDstLL7QDG6): commit status **success**; application domain reachable after rollout.
- Final source: **1,180 provider-free tests passed**, four live tests deselected, 30 deprecation warnings. No runtime change followed that gate.

Post-rollout command `output/http_smoke_20260908.py` observed healthz 200
(7.672 s), readyz 200 (0.843 s), guest admin 401/no-store (0.329 s), guest
settings 401 (0.343 s), private workspace 404 (0.563 s), guest chat
401/demo_login_required, invalid login CSRF 403. Individual timings are not a benchmark.

An additional browser request enabled the optional guardrail, using synthetic
text `Kiểm chứng dependency guardrail 20260908`. It exercised the missing-import
branch before generation, not another paid model attempt. Admin trace
`4f2bd854-a7aa-4a95-9b60-9581fd1b4419` showed technical_error,
GuardrailUnavailableError, stage guardrails_input, message
`input guardrail unavailable: dependency_unavailable`, elapsed 0.2183 s,
zero LLM-call records, zero external-service records and zero stored contexts.

These are transcribed admin observations, not raw API exports. The route regression
proves HTTP 503; production browser evidence proves the typed persisted failure.
The exact production HTTP response status was not separately captured. Missing
usage remains N/A. Source and regression establish no retrieval/generation in this
specific missing-import path. Full guardrail execution remains unavailable until
NeMo packaging/hosting is resolved. Admin input/output boolean defaults are not
proof of successful guardrail execution; inspect request status and error stage.

Report/full-review browser evidence on 20d0159 remains in README.md; paid calls
were not repeated after the guardrail-only change. NVIDIA/Groq availability,
two-user/email acceptance, complete source discovery, OCR/storage and legal-quality
acceptance remain open. This addendum changes documentation only.
