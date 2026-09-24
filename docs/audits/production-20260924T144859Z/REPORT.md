# VietLex production audit — 24 September 2026

## Scope and identity

Production tested: `https://vietlex-legal-rag.vercel.app` in a real Codex in-app browser. Audit began 2026-09-24 14:48:59 UTC (21:48:59 Asia/Bangkok). Desktop 1366×768 and mobile 390×844 were sampled. The production deployment commit **could not be verified**. Local Git HEAD was `2da3d125dcf3febe22126b3fe9f9572e67c3921c`; the tree was already dirty (`.codex/config.toml` modified and pre-existing untracked files). Local source was used to explain possible mechanisms, never as substitute for production behavior or proof of a deployment match.

This audit created only the new directory `docs/audits/production-20260924T144859Z/` locally. On production it created two labeled test workspaces (the second for isolation), three source pins, two clearly labeled synthetic TXT documents, a five-clause review/findings record, a report draft/version and a chat session. It did not edit source/config, production credentials, underlying corpus, existing user data, roles or quota; it did not commit, push, deploy, ingest or migrate.

## Executive assessment

The sampled **search → official source → saved excerpts → selected-evidence answer** path worked, with appropriate warnings that the 2019 text's current effect was not established. A mobile **search → document reader → section-scoped chat** path gave the correct 85% probation-salary threshold against the cited 2019 text. A test-only **TXT upload → five-part plan → batch review → persisted findings** path also worked and distinguished supported from unsupported findings. These are narrow production observations, not a reproducible full-corpus retrieval benchmark or a legal correctness certification.

The main broken step is **AI report generation**. The audit's attempt yielded an empty, unverified body because the model used an ID outside the selected evidence; the guard correctly blocked it. Read-only admin telemetry for the same UTC date showed seven retained structured-report requests, all seven ending `research_report_invalid_structured_response`. The audit failure alone consumed 2,054 provider-reported tokens. Investigate this before treating report generation as usable. Markdown/DOCX download events occurred after a manual edit, but the downloaded bytes were not accessible for content verification.

The user's token-cost concern is justified as an audit criterion. VietLex already has real bounded-context paths, yet cost visibility is uneven. The production source-analysis screen reported **10/37** passages selected from 25,673 saved characters and returned a correct four-item Điều 120 answer, while the admin list omitted that LLM call. Other audited admin traces measured 423 input tokens for one document-scoped chat, 1,668 input for the five-clause review, and 1,260 input for the failed report. Passage count and whitespace-word limits are **not** provider token counts; those measured examples must not be extrapolated into an overall cost-saving percentage.

## What users could do in the sampled journeys

| Journey | Result | Evidence |
| --- | --- | --- |
| Search a document number and open a mobile reader | One correct corpus hit; TOC jump to Điều 26; scoped chat answered 70% vs 85% correctly and restored after reload | C02/C10, E06/E08 |
| Search a nonexistent internal document number | Empty state warned that no internal hit does not prove absence of a legal rule | C17, E10 |
| Filter a known number by its displayed type and authority | Authority retained the result; entering the card's `LUẬT` type hid it while `Luật` restored it | C18, E11/F06 |
| Search an ordinary legal issue and open official PDF | Five keyword suggestions; official Công báo PDF found, 12 of 94 pages read in groups, Điều 119/121 pinned | C03/C04, E01/E03 |
| Use selected evidence to answer a multi-part follow-up | Correct 10-day filing/15-day effect from two selected excerpts; current effect explicitly left uncertain | C05, E07 |
| Ask a saved source about Điều 120 with relevant passages | 10/37 passages selected; answer listed four dossier items with the right two adjacent PDF excerpts | C06, E02 |
| Upload and review a synthetic policy | Unicode TXT separated into preamble + four articles; one batch covered 5/5 and saved three findings | C11, E05 |
| Keep workspace evidence separate and reject invented quotes | Empty workspace B did not inherit A's pins/documents; an invented quote failed to pin | C14–C15, E09 |
| Generate and hand off a research memo | Generated body failed validation; manual new version saved; export events occurred but file content unverified | C07–C09, E04/E08 |

## Legal source cross-check and limits

The [official Công báo PDF](https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2019/11/30232/29070-1-2019993-99445-2019-qh14.pdf) has a `BỘ LUẬT LAO ĐỘNG` cover. Its printed pages 51–52 (PDF pages 49–50 in the product reader) contain Điều 119 (employers with at least 10 workers register at the provincial labor authority where registered; filing within 10 days), Điều 120 (four listed filing documents), and Điều 121 (effect 15 days after competent authority receives a complete dossier). Điều 26 on the same official text gives at least 85% of the job salary during probation. The [official portal record](https://congbao.chinhphu.vn/van-ban/nghi-quyet-so-45-2019-qh14-30232.htm) publishes 20/11/2019 as issue date and 01/01/2021 as initial effective date, but its metadata title incorrectly uses `Nghị quyết ... bộ luật Lao động`; the PDF itself resolves the instrument type. The audit did **not** verify every amendment, repeal or transition rule through 24/09/2026. Findings about a hypothetical 2026 policy therefore remain source-text comparisons, not final current-law advice.

## Token and relevance controls: current evidence and concrete next steps

### Current controls observed or source-validated

- Document-scoped chat selected one 332-character Điều 26 excerpt; admin measured 423 input/236 output provider tokens for that call (C10/C13). Local `app/services/document_scope.py` uses structural chunks and query ranking, with settings for 220 approximate-token chunks, up to three final chunks and a 720 whitespace-word context budget. The admin trace corroborates one selected context for this case, not the full algorithm on production.
- Manually selected-evidence analysis kept exactly two chosen excerpts through tab navigation and used a documented 10-evidence / 4,000 whitespace-word / 20,000-character cap (`app/services/research_analysis.py`, `app/config.py`). The answer did not silently add an unselected source in the sampled case. This is a cap, not a measured billed-token guarantee.
- Retained-source analysis defaults to **relevant** in the observed library form (`app/templates/workspace_source_library.html`). Local `relevant_source_passages` scores query-term overlap and headings, includes adjacent text after a matching heading, and caps selection at ten passages. C06 selected 10/37 and preserved both halves of Điều 120. This is query-dependent generic selection, not a hard-coded list of legal topics. The server route's fallback default is `full` if a caller omits scope; the UI submitted `relevant` in this case.
- Full-document review batched five extracted units into one call, measured at 1,668 input/670 output provider tokens. Local batching uses a 720 whitespace-word budget for clause text and repeats chosen legal evidence across batches (`app/services/full_document_review.py`). Scaling to long documents was not measured; source structure suggests cost rises with batch count.
- Admin reports provider token usage where available, but its aggregate excludes some workflows and services. The retained-source LLM call was absent from the central request list; the local route stores provider calls in its workspace analysis record. F05.

### Smallest effective improvement sequence, without topic-specific hard coding

1. **Make every LLM task measurable.** Log per-call provider input/output tokens, task type, selected passage IDs/count, source page range, budget, latency, outcome and an input-content hash. Exclude raw private text from the central cost log. Mark usage N/A when provider omits it, and reconcile daily totals with every LLM workflow. This addresses F05 before any cost claim.
2. **Use a common query-aware evidence selector.** Parse generic legal references such as document number, Điều/Khoản/Điểm and date from each query; select matching structural units first, then lexical/sparse/dense candidates as appropriate to the existing retrieval contract. Rank, deduplicate and diversify, include adjacent conditions/exceptions, and pass only the selected units plus compact metadata to the model. The parser should not contain fixed statute names, topics or answer strings. Keep user-selected evidence as an explicit hard scope.
3. **Enforce a provider-token budget before each call.** Current whitespace/character caps are useful guardrails but do not equal billed tokens. Count with the deployed model tokenizer or provider-supported token-count API when practical; reserve output tokens and system instructions, then reduce context by rank without cutting clauses mid-condition. If sufficient evidence does not fit, split a review into auditable batches or return an explicit insufficiency result. Avoid the `full` source route as an implicit default for new callers.
4. **Avoid repeated context in multi-batch work.** Keep a stable legal-evidence index and include only excerpts relevant to each clause batch, with a small shared set only when necessary. Measure input-token growth against batch count and citation coverage. Do not memoize a legal conclusion across different dates or source versions without a verified cache key.
5. **Gate on quality and cost together.** Build a human-checked evaluation set spanning exact references, paraphrases, typos, multi-clause conditions, exceptions, date changes, cross-page excerpts and no-answer cases. Compare Recall@K, article/clause coverage, citation precision, unsupported-claim rate and provider input tokens to the current baseline on identical questions. Promote a change only if cost drops without material retrieval or legal-support regression. No new embedding/provider/vector contract should be switched without its required A/B and migration authorization.

Tavily could help discover candidate official URLs, but C03 already reached an official PDF; neither Tavily nor a wider web search alone decides current legal validity or reduces model input. Add it only after an identical-question A/B shows better official-source recall or lower total cost, and keep original-PDF checking and passage budgeting.

## Priorities

1. **Verified failures to fix:** F03 (P1) recurring report-generation validation failures with measurable wasted tokens; preserve the validator. F02 (P2) stale pin count after same-page success. F04 (P2) admin generic code checks falsely mark a successful structured review as failed. F05 (P2) central token telemetry omits retained-source analysis. F06 (P2) the displayed document type fails its own exact filter because letter case changes the match.
2. **Evidence-backed UX:** F01 (P3) library wording should distinguish unread pages from attempted pages without extractable text. The official-portal title conflict should be disclosed when PDF cover and metadata disagree.
3. **Investigate before changing retrieval:** reference-only relevance for saved sources, long-document batch cost, citation mapping for derived chat claims, report model-output reason distribution, and current-law status. Require the same benchmark questions and provider token usage before/after any selector change.
4. **Product/data decisions:** topic/body search remains limited to number/title and 20 displayed hits; full corpus coverage in the v3 Qdrant collection is not established by this audit. Choose the intended coverage contract before promising broad topic retrieval.

## Coverage, evidence and unrun work

See [COVERAGE.md](COVERAGE.md) for every inventoried feature and status, [CASES.md](CASES.md) for inputs/expected/actual results, [FINDINGS.md](FINDINGS.md) for reproduction and acceptance criteria, [OBSERVATIONS.md](evidence/OBSERVATIONS.md) for UI transcripts and trace URLs, and [manifest.json](manifest.json) for audit identity. Many independent features remain NOT TESTED, including PDF/DOCX upload, scan OCR, cross-account authorization, source A/B comparison, legal-effect promotion, report file contents and print-to-PDF. No full benchmark, integration suite or live ingestion was run.

## Commands and evidence classes

Read-only local inspection included these exact commands (plus bounded `Get-Content` reads of the named project files):

```powershell
git rev-parse HEAD
git status --short --branch -uno
rg -n '@(router|app)\.(get|post|put|patch|delete)\(' app/api | Select-Object -First 160
rg -n 'FINAL_EVIDENCE_LIMIT|QUERY_CHUNK_MAX_TOKENS|LLM_CONTEXT_MAX_TOKENS|context_selection|usage_metadata|input_tokens|prompt_tokens|retrieval_trace|llm_context|build_context|select_final' app | Select-Object -First 140
Get-Date -AsUTC -Format o
Get-FileHash -Algorithm SHA256 -LiteralPath 'docs/audits/production-20260924T144859Z/evidence/AUDIT-TEST-NOT-REAL.txt'
Get-FileHash -Algorithm SHA256 -LiteralPath 'docs/audits/production-20260924T144859Z/evidence/AUDIT-NOI-QUY-MAU-UTF8.txt'
```

CRG was checked first and had no callable tools in this session, so bounded `rg`/source reads were used. Production evidence came from actual browser UI interactions and admin request details. Official-source text was checked against the Công báo record/PDF. **Unit tests NOT RUN; integration tests NOT RUN; live-provider browser runs performed as listed in CASES.** A source or configuration change was neither requested nor made.

## Git and external effects at close

The audit directory and its labeled test inputs are new local files. Pre-existing dirty/untracked items were left intact. Production holds the two labeled audit workspaces and associated test artifacts listed above; no existing user-owned record was edited or deleted. No commits, pushes, deployments, credentials changes, corpus ingestion, migrations or provider upgrades were performed.
