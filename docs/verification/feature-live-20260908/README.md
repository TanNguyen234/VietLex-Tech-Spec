# VietLex functional verification — 2026-09-08

**Deployment follow-up:** [final runtime rollout evidence](rollout.md) resolves the creation-time pending state below.

Deployed runtime source: `20d0159ef2022d54450910d6238d6bfabc963142`, following
`d7ec81cad557c4cfcf44aa082ee20470e82e4c0d`. This is a small operational verification,
not a legal-quality benchmark or production-readiness certification.

Additional local runtime fix: `8cbd948` (guardrail dependency import failure).
It passed the final suite below; deployment evidence for this commit is **PENDING**
at report creation. Earlier browser results are explicitly tied to `20d0159`.

## Delivered and verified

- Structured-report failures now retain bounded validation locations/types,
  finish reason and provider-reported usage without retaining validation inputs.
- A live verifier reached `MAX_TOKENS` at the previous 2,000-token cap:
  1,746 thinking and 250 output tokens, followed by `json_invalid`. Report and
  verification use a finite 4,096-token cap; truncation fails explicitly without
  an automatic regeneration. A subsequent successful verifier used 2,249 thinking
  and 292 output tokens, exceeding the old cap.
- A separate contract-review response finished with `STOP` but contained a
  Markdown JSON fence. Its body satisfied the existing schema. Structured Vertex
  calls now request `application/json`; parsers remain strict. The corresponding
  live check passed with two findings (602 input, 331 output, 1,432 thinking,
  2,365 provider-reported total tokens).
- Invalid clause references in full-document review are handled as typed failures;
  they do not advance coverage. Known structured failures are recorded in admin
  technical-error fields for new requests. Old records are not backfilled.
- Provider-free full suite: **1,180 passed, 4 deselected, 30 warnings**, 255.50 s.
  The additional guardrail regression reproduced `ModuleNotFoundError` before the
  fix; missing optional guardrail imports now produce the existing typed 503 and
  persisted technical error without retrieval/provider execution. NeMo is still
  excluded from the small serverless package; this fix does not enable it.
  Ruff, diff whitespace and repository-artifact checks passed. See [commands](commands.md).
- [CI 34252348259](https://github.com/TanNguyen234/VietLex-Tech-Spec/actions/runs/34252348259):
  test-and-lint and Docker build-and-push both succeeded for `20d0159`.
- [Vercel deployment](https://vercel.com/foxys-projects-5fe642e0/vietlex-legal-rag/EicaxBuBCg9EVZWHn97RunZ1iT9Z)
  is Ready in Production, source `20d0159`, domain
  [vietlex-legal-rag.vercel.app](https://vietlex-legal-rag.vercel.app).
  Immutable deployment hostname: `vietlex-legal-ilcuefbbw-foxys-projects-5fe642e0.vercel.app`.
- Post-deployment browser full review completed **2/2 clauses**, with no selected
  legal authority and explicit human-review caveats. Post-deployment report
  returned the synthetic delivery date **15/09/2026**, linked selected evidence,
  and appeared in saved analysis history.

The original handoff's first-generation `ResearchReportValidationError` cannot be
retrospectively attributed to either observed cause: its diagnostic response was
not retained. One earlier verifier failure in this session also lacked sufficient
diagnostics. Successful later calls do not prove those unknown failures resolved.

## Feature matrix

“Tested” below distinguishes provider-free contracts from live service calls and
browser integration. Tests use doubles at external boundaries unless explicitly
identified as live. Legal correctness remains unaccepted without labeled expert
review, even where the synthetic date matches exactly.

| Feature | Current implementation / provider-free evidence | Live or browser evidence | Remaining limits / next action |
|---|---|---|---|
| Guest admission, CSRF | Route/RBAC/demo tests in full suite | Guest admin/settings 401; private workspace 404; guest chat 401 `demo_login_required`; invalid login CSRF 403 | No load or quota-exhaustion test |
| Signup, verification, recovery, login | Account/session tests pass | Existing verified admin session used; no new email sent | **NOT RUN** email lifecycle and login-again; user elected to self-check email; no test mailbox supplied |
| Two-user isolation, account operations | Owner/session/RBAC tests pass | Guest cannot retrieve test workspace | **NOT RUN** two verified users, revoke/disable/delete/export admin; only protected admin available |
| Search and full document | Legal browser tests pass | Number `59/2020/QH14` finds Luật Doanh nghiệp 2020; `/documents/427301` renders full text and outline | This is number/title lookup, not verified article/body search |
| Chat, retrieval, streaming, guardrails | Existing chat, progress, retrieval and guardrail tests pass; historical bounded live RAG evidence separate | This session's browser guarded chat returned “Yêu cầu chưa hoàn tất”; Vercel logs later confirmed HTTP 500, request `6kcwj-1788885509481-7820114bda39` | **NOT VERIFIED end-to-end**; missing NeMo import reproduced locally and fixed fail-closed in 8cbd948; deployed response still needs verification; do not count historical chat as this test |
| Workspace, evidence, persistence | Research database/owner tests pass | Created synthetic workspace; pinned clause; files, evidence, report, redline and timeline survive reload | Login-again and two-user persistence **NOT RUN** |
| TXT/DOCX/PDF upload | Extraction/worker/route tests pass | Three real synthetic files parsed: TXT 219 bytes/180 chars/2 clauses; DOCX 36,746 bytes/180 chars/2 clauses; PDF 1,445 bytes/101 chars/1 clause | Small text PDF only; scanned PDF/OCR **NOT IMPLEMENTED**; original files not retained |
| Selected evidence / obligations / evidence-group comparison | Strict provenance, modality, context-budget tests pass | UI present; standalone AI actions **NOT RUN** in bounded call allowance | Need individual synthetic E2E acceptance; model comparison is a different feature |
| F01 semantic claims | Strict quote/reference/coverage schemas; report live integration passed with 2/2 assessed claims | Report and claim-assessment pipeline executed; source links rendered | No expert-labeled support/contradiction acceptance corpus; not legal certification |
| F02 legal effect/freshness | Provenance and human-review workflow exists | Admin form visible; no legal facts promoted | Human-only authoritative review **NOT RUN**; unknown remains unknown |
| F03 trusted sources | Allowlisted HTTPS origins, redirect/size/script/reconciliation tests pass | Internal URL form attempt returned generic failure, without inspected network response | UI failure alone does not prove SSRF rejection; positive `https://baochinhphu.vn/` read succeeded, title/text result saved; legal-document completeness not accepted |
| F04 deep research/report | Deterministic bounded five-step plan and report schema/coverage tests pass | Public-Qdrant report service probes; synthetic integration; browser report before and after latest deploy succeeds | Five-step plan/execution ran with all five `NO_RESULTS`; no sources discovered; limited selected-source synthesis, not exhaustive legal research |
| F05 OCR/large storage | Isolated parser with deadline/memory limits, bounded text stored in workspace | Small supported uploads succeed | OCR/object store requires separate resource/retention design; see [remaining work](remaining-work.md) |
| F06 full review/redline | Bounded batch plan/progress and deterministic diff tests pass | Review 2/2 clauses on latest deploy; TXT/DOCX redline shows one changed clause, one unchanged, 4/4 compared | Review finding text may be wrong; no contractual/legal correctness claim; no large-document acceptance |
| F07 timeline | Deterministic dates/provenance tests pass | 2026-09-15 linked to exact `15/09/2026` source; 1/1 source, one event, zero unknown | Relative/ambiguous legal deadlines not live accepted |
| F08 model comparison | Two exact models, same-input hashes, bounded calls, missing usage explicit | Latest NVIDIA and Groq attempt both `provider_unavailable`; failure result saved; no response/usage | **BLOCKED provider availability**; earlier UI attempt had no persisted result; no ranking or success claim |
| F09 admin accounting | Request ledger, coverage, admission/quota projections; new failure mapping regression | Admin details and real report/review usage visible; account/config/quota sections inspected | Billing money and all embedding/reranker/retry usage incomplete; process counters not global; no guessed costs |
| F10 evaluation/corpus | Expanded deterministic tests and artifact-driven evaluation views exist | Full provider-free suite succeeds; no new quality benchmark | Historical v3 scope 14,962 docs, not 518,255; answer baseline failed; migration/full ingestion/large benchmark **NOT RUN** |
| WAF | Application controls do not prove edge protection | Vercel dashboard: Bot Protection **Off**, AI Bots **Allow**, no custom/IP-block/system-bypass rules | No rules changed; edge policy requires explicit operational decision |
| Security limits/failure paths | Tests cover upload/archive limits, owner scope, budgets, provider errors, timeouts, SSRF and safe presentation | Literal `<script>alert(1)</script>` in synthetic document/review rendered as text; CSRF and guest denials observed | No flood, penetration test, quota depletion, concurrency/load test or backup restore |

## Evidence and remote effects

Synthetic workspace: `524d5a44-41b6-41ac-964d-7c73ebaeb284`, named
`VietLex verification 20260908`, created 2026-09-08 15:57:34 UTC and shown with
retention until 2026-10-08 15:57:34 UTC. Test uploads/evidence/analyses remain there.
No real user documents were uploaded, altered or deleted. No admin password,
credential, persistent corpus/index/database migration or WAF configuration changed.

Read-only Vercel runtime logs also showed `Failed to export span batch code: 401,
reason: Unauthorized` on successful page/readiness requests. This is evidence of
failed telemetry export, not proof that those HTTP requests failed. Logfire being
configured does not establish working trace export; no credentials were changed.

Earlier browser request traces: report
`ae69284c-28a5-4d3a-8e96-754e82726f50` (3,993 reported tokens, 2/2 calls with usage);
failed pre-fix review `e4b71c50-57b1-44fe-9373-68fed0dc5bcd`
(1,722 reported tokens, 1/1 calls with usage). These totals exclude unreported
upstream activity and are not monetary cost. Historical admin rows are not this
session's test outputs.

The additional direct user-approved allowance was at most 12 generation calls,
without automatic retries. Conservative reservation: diagnostic review 1; first
NVIDIA/Groq UI attempt 2 (actual execution unknown); post-fix service review 1;
guarded chat up to 3 (execution unknown); post-deploy review 1; report up to 2;
last NVIDIA/Groq comparison 2. All 12 slots reserved; **no further calls**.
Unknown attempts are not reported as successfully billed calls. Earlier authorized
report probes and synthetic integration preceded this additional allowance.

Sources for transport semantics:
[Vertex response finish reasons](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/GenerateContentResponse)
and [JSON response MIME configuration](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1beta1/GenerationConfig).

## Git scope

The first two runtime commits were pushed to main with direct confirmations where automatic
approval review required them. Changes outside this task remain untouched:
`.agents/skills/writing-plans/SKILL.md`, `.codex/config.toml`, `build/`,
`vietlex_online_ssr.egg-info/` and four pre-existing evaluation run directories.
The working tree is therefore **dirty**. This report does not promote an evaluation
manifest or claim a clean-tree benchmark. Local test XML is under ignored `output/`.

See [commands and changed files](commands.md) and [remaining work](remaining-work.md).

Latest production admin evidence on 20d0159: report `04870f47-a7b8-433b-82df-4bdea40cfe5a` = **3,020 total tokens, 2/2 calls with usage**; full review `3ffc59e4-8c40-464e-9ea9-97383888b2b9` = **2,253 total tokens, 1/1 call with usage**. Model comparison `17ab3904-90ba-4b6a-afa7-c91fd209f960` = partial, **0/2 calls with usage**. Deep research `b6b3ec4b-6552-47e0-b125-5e4647b85683` = failed/no results, **0/0 LLM calls**. No monetary cost inferred.
