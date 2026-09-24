# Production feature coverage

Status refers only to the behavior sampled in this audit, not to source-code existence. Case IDs link to `CASES.md`; `E01`–`E10` link to `evidence/OBSERVATIONS.md`. A feature listed as NOT TESTED is inventoried but has no production outcome claim. Local route inventory used `rg` on `app/api`; the deployment commit is unknown.

| Group | Feature | Status | Production evidence or reason |
| --- | --- | --- | --- |
| Navigation | Homepage and top navigation | PASS | Home/search/workspaces/account links visible and navigated; C01–C03. |
| Navigation | Desktop layout sampled at 1366×768 | PASS | Report page, no measured horizontal overflow; E06. |
| Navigation | Mobile layout sampled at 390×844 | PARTIAL | Search, reader, report usable; not every view or keyboard path tested; E06. |
| Search | Exact document number | PASS | C02. |
| Search | Topic/title search | PARTIAL | 20 capped title/number results, body search unavailable by UI disclosure; C01. |
| Search | Type filter matching displayed type | FAIL | `LUẬT` from the result card suppressed the same known result; `Luật` restored it; C18/E11/F06. |
| Search | Issuing-authority filter | PASS | `Quốc hội` retained the known 45/2019/QH14 record; C18/E11. |
| Search | Date filters and ordering | NOT TESTED | Controls visible, no verified date/sort case. |
| Search | Empty result | PASS | Implausible number produced a scoped, honest empty state; C17/E10. |
| Search | Pagination beyond 20 results | NOT TESTED | Max-20 boundary visible; no beyond-first-page run. |
| Reader | Structural TOC and section jump | PASS | 237 sections, mobile Điều 26 jump; C10. |
| Reader | Public source link, exact quoted section | PASS | Điều 26 and official PDF cross-check; C10. |
| Reader | Pin internal section | NOT TESTED | Route inventoried; no run. |
| Chat | Document-scoped answer | PARTIAL | Correct 85% conclusion, direct citation mapping 1/5 displayed claims; C10. |
| Chat | General natural question over full corpus | NOT TESTED | Production chat was document-scoped in C10. |
| Chat | Session reopen after reload | PASS | C10. |
| Chat | Feedback, rename, export, deletion | NOT TESTED | Routes inventoried; no run. |
| Workspace | Create audit workspace | PASS | C03; ID in manifest. |
| Workspace | Edit metadata, expiry, delete | NOT TESTED | No destructive action; expiry not reached. |
| Workspace | Source selection persists across tabs | PASS | Two selected evidence IDs persisted; C05/E07. |
| Workspace | A/B comparison-group selection | NOT TESTED | Controls inventoried; no comparison run. |
| Workspace | Isolation of evidence across two workspaces | PASS | New B had 0 evidence/docs/reports; A retained 3 evidence/2 docs; C14/E09. |
| Source research | AI keyword suggestions, user editable | PASS | Five suggestions rendered; C03. |
| Source research | Official search result relevance | PARTIAL | Official source found alongside unrelated metadata hits; C03. |
| Source research | Original official PDF reading | PASS | PDF read 12/94 pages; C03/E01. |
| Source research | Full official HTML body reading | NOT TESTED | Portal metadata opened; no distinct HTML full-body extraction case. |
| Source research | PDF continuation in max-five-page batches | PASS | Three page groups produced 12 unique retained pages; C03. |
| Source research | Scanned PDF OCR | NOT TESTED | No known scan used; paid API path not invoked. |
| Source research | Saved-source reopen without AI | PASS | Stored reader reopened; E01. |
| Source research | Read/unread page labeling | FAIL | 82 unread pages labeled as having no text in retained reads; C03/F01. |
| Source research | Exact quote pin and persistence | PARTIAL | Quotes persisted, two same-page counters stale until reload; C04/F02. |
| Source research | Reject fabricated pinned quote | PASS | Invented 99-day quote rejected; pin count stayed three; C15/E09. |
| Source research | Search within saved source | PASS | Exact phrase matched PDF pages 49–50 from 12 saved pages; C16/E09. |
| Analysis | Selected-evidence answer | PASS | Two-scope answer with exact citations and limits; C05. |
| Analysis | Retained source relevant passage selection | PASS | 10/37 selected, Điều 120 answer supported; C06. |
| Analysis | Retained source full-read mode | NOT TESTED | UI option available but deliberately not run because it may increase AI input. |
| Analysis | Compare evidence A/B | NOT TESTED | No two distinct legal sources grouped. |
| Analysis | Obligations, legal timeline, legal effect | NOT TESTED | Routes/UI inventoried, no verified run. |
| Analysis | Claim verification, model comparison | NOT TESTED | Routes/UI inventoried, no verified run. |
| Analysis | Source legal-effect event browsing | NOT TESTED | UI disclosed; current status remains unknown. |
| Documents | Upload TXT, extract Unicode clauses | PASS | Five extracted units; C11/E05. |
| Documents | ASCII heading variant | PARTIAL | One part; behavior measured, unsupported contract status unknown; C12. |
| Documents | Upload PDF/DOCX, OCR, unsupported file | NOT TESTED | Only TXT uploaded; no scan/OCR or invalid format. |
| Documents | Original download | NOT TESTED | Link visible, bytes not inspected. |
| Documents | Pin document clause, remove document | NOT TESTED | Avoided deletion; pin unrun. |
| Review | Full-document batching and coverage | PASS | One batch, 0/5→5/5, zero unscheduled; C11. |
| Review | Legal findings with selected evidence | PASS | Two intentionally wrong clauses linked to correct excerpts; C11. |
| Review | Unsupported finding handling | PASS | Third finding marked needs verification without direct selected legal citation; C11. |
| Review | Persist/reopen findings | PASS | Saved findings list and 3/3 page after reload; E05. |
| Review | Decision notes/status/history | NOT TESTED | UI inspected, no decision written. |
| Review | Redline between two uploads | NOT TESTED | Controls inspected, no run. |
| Report | Generate draft from selected evidence | PARTIAL | 1/1 generation failed evidence-ID validation; safe guard did not promote output; C07. |
| Report | Edit/version/reopen draft | PASS | New unverified version, prior link; C08. |
| Report | Markdown and DOCX export event | PARTIAL | Download events fired; file content unavailable; C09. |
| Report | Print/save PDF | NOT TESTED | No printed artifact inspected. |
| Account | Signed-in account view | PARTIAL | Existing authenticated session used; no other account or role tested. |
| Account | Register/login/logout/reset, privacy export/delete | NOT TESTED | Outside non-destructive one-session path. |
| Admin | Dashboard, requests and request-detail token view | PARTIAL | Read-only dashboard and three request details inspected; C13/E08. |
| Admin | Usage/providers/system/stats/logs/users/audit | NOT TESTED | Routes inventoried; no verified page audit or mutation. |
| Admin | Corpus/feedback/evaluation lab/legal registry | NOT TESTED | Routes inventoried; no benchmark or human legal promotion. |
| Operations | Quota/rate-limit/provider error path | NOT TESTED | No quota exhaustion or induced provider fault. |
| Operations | Health/readiness/progress streams | NOT TESTED | Route existence only; HTTP status alone would not establish a user journey. |
| Security | Cross-account authorization | NOT TESTED | Only one existing session; no cross-account test. |
| Efficiency | Selected-evidence context cap | PARTIAL | UI and local source show 10 evidence / 4k whitespace words / 20k chars; actual production payload/token count not observed; C05. |
| Efficiency | Dynamic source passage choice | PARTIAL | Visible 10/37 passage choice answered Điều 120; retrieval recall across varied legal questions and provider token count unmeasured; C06. |
| Efficiency | Provider-reported tokens for scoped chat | PASS | 423 input + 236 output in admin detail; one case, excludes other service charges; C13/E08. |
| Efficiency | Full-document review token cost | PARTIAL | One 5-clause batch measured 1,668 input + 670 output; no long-document scaling measurement; C13/E08. |
| Efficiency | Report failure token overhead | FAIL | Failed audit report consumed 1,260 input + 794 output provider tokens with no usable body; 7/7 retained report requests that day had invalid-structured-response status; C07/C13/E08. |
| Efficiency | Retained-source provider token observability | PARTIAL | Passage count visible, provider calls saved with workspace analysis in local source, absent from admin request list; C06/C13/E08. |
