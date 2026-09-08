# Concrete remaining work and acceptance boundaries

This replaces neither the historical backlog nor the approved plan. It records
what this verification could not finish; implementation presence is not acceptance.

1. **Chat/guardrail E2E:** Vercel request `6kcwj-1788885509481-7820114bda39`
   returned HTTP 500 on d7ec81c. The small serverless package excludes NeMo and
   its configuration; local import-failure regression reproduced an unhandled
   ModuleNotFoundError. Commit 8cbd948 converts missing imports to the existing
   typed/persisted 503 and prevents retrieval. Verify that response after deployment.
   Full guardrail execution still requires a packaging/hosting decision and a new
   bounded live allowance; this is not a working guardrail acceptance claim.
2. **NVIDIA/Groq comparison:** both latest browser responses were
   `provider_unavailable` with no observed model or usage. Check sanitized provider
   errors and provider access/quota before a new two-call acceptance run. Do not
   change credentials or infer that a configured key proves service availability.
3. **Authentication acceptance:** user elected to verify emails independently.
   Two verified non-admin test accounts and accessible mailboxes are still needed
   for signup/verification/recovery/login-again and cross-owner read/write/delete
   tests. Preserve the sole existing admin account. Guest denials and unit tests
   are not substitutes for this acceptance.
4. **Other AI surfaces:** selected-evidence answer, evidence-group comparison,
   obligations and standalone claim verification need bounded UI cases after
   provider/transport readiness. Shared services/tests and report success do not
   prove every form. Deep research executed five queries but all returned NO_RESULTS; positive HTML
   read at baochinhphu.vn succeeded. Source discovery and complete legal-document
   extraction still need representative acceptance cases.
5. **F05 proposal (not deployed):** retain current small text upload as default;
   add an opt-in asynchronous OCR lane with private object storage, per-owner
   object keys, signed short-lived access, queued isolated worker, page/byte/time
   caps, idempotent job state, source hashes and page provenance. Apply the same
   workspace retention to originals, extracted text and failed-job payloads.
   Suggested first acceptance scope: five public/synthetic scanned PDFs, <=10 pages
   each; compare text/diacritics, dates, numbers, page references, runtime and
   actual OCR usage. Before implementation/deployment select storage/OCR service,
   region, cost ceiling, worker host and deletion/retention mechanism. Creating
   buckets/queues, changing credentials and migrating existing records are not
   authorized by current code/push permission. No corpus migration is needed for
   an isolated future OCR lane.
6. **F09 accounting:** record provider-reported embedding/reranker/attempt usage
   with its own coverage, and reconcile billing only against an actual provider
   export. Keep missing values missing. Persist admission counters if a global
   dashboard is required; current process counters reset on restart.
   Vercel logs showed span-export `401 Unauthorized` on otherwise successful
   requests. Resolve the exporter authorization with the account owner before
   claiming end-to-end observability; credentials were not changed here.
7. **F10 benchmark:** first freeze a small expert-labeled acceptance dataset with
   support/contradiction/insufficient, legal-effect dates, multi-hop citations and
   refusal cases. Approve identical-input A/B configuration and monetary budget
   before any live quality run. Save immutable manifest/revision/hash/dirty proof.
   Full corpus expansion requires a separate explicit ingestion/migration plan;
   current audited v3 coverage remains 14,962 documents.
8. **WAF decision:** observed Bot Protection Off, AI Bots Allow and no custom
   rules. A reviewable next policy can start with logging for auth/upload/AI
   endpoints and measured rate thresholds, then narrowly challenge or block
   abusive sources. Test reviewer access before enforcement. No paid plan upgrade,
   rule mutation or traffic flood was made during this task.

Legal-effect evidence promotion and legal correctness remain human decisions.
Large-load/concurrency, backup restore and penetration tests remain NOT RUN.
