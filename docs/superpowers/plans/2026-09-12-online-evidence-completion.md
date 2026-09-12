# Online evidence completion implementation plan

**Goal:** Users without internal corpus evidence can discover, read and pin official provisions, then analyze those exact sources, with measured real-provider outcomes.

**Architecture:** Keep v3 retrieval/index contracts unchanged. Add bounded keyword planning through the existing generation adapter, preserve editable plans and typed failure metadata. Extend the existing approved reader to official document attachments and connect discovery to persisted exact excerpts and existing selected-evidence analysis.

**Authority:** User authorizes runtime fixes, real/paid provider calls, split commits and push; prior deployment authorization persists. No full ingestion, index deletion, credential changes or automated legal-effect promotion. Sequential execution; no subagents/worktrees.

## Acceptance and scope

- [x] Freeze the existing ten cases and add holdout natural queries before tuning. Verify discovery by exact expected URL, distinguish finding a title from reading provisions and answering the question.
- [x] Planner: `app/services/official_query_planner.py`, `deep_research.py`, workspace plan endpoint. RED tests: natural question is not reduced to trailing date; provider failures visible; newly invented legal reference rejected; user-edited plan preserved.
- [x] Reader: `trusted_source_reader.py` and focused tests. Approved government PDF origins only; no redirects, auth bypass, unbounded downloads or navigation boilerplate as legislation. Preserve original URL, attachment URL, hashes, page numbers, truncation and unknown effectivity. Scanned PDFs without usable text return explicit extraction-needed status.
- [x] Workflow: discovery → read selected official source → exact excerpt pin → selected-evidence analysis. Reuse owner/CSRF/quota/persistence checks. UI exposes gaps, not an automatic claim of research completeness.
- [x] Review stable diff and failure paths. Focused RED/GREEN before each behavior change; full provider-free suite after stable review.
- [x] Real before/after ten-case and holdout evaluation, manifest with exact Git state/diff hash, inputs, config fingerprint, provider metadata, outputs and skips. Legal correctness cannot be inferred from HTTP success or title matching.
- [x] Update status/report only after stable verification. Commit runtime/UX/evidence separately and push. Confirm actual remote state.

**Non-goals:** Adding providers merely for count; auto-certifying current law; fabricating full corpus coverage; bypassing production quotas; training to the ten reference document numbers.
