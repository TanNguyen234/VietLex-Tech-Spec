# VietLex CV / Portfolio Evidence

Current evidence date: 2026-09-02.

## CV bullet — English

Built and reproducibly evaluated a Vertex/Qdrant v3 Vietnamese legal RAG
pipeline on 50 QA cases. The retrieval audit scored 40 cases with verified
required evidence and achieved Document Recall@3 **53/53**, Article Recall@3
**30/30**, Clause Recall@3 **13/14**, all-required coverage **39/40**, and zero
retrieval/reranker technical errors. The separate answer audit completed 50/50
generations and guardrail checks; Ragas scored 49/50 with one typed judge error.
Deterministic token F1 remained **0.230**, so the result is bounded evidence, not
whole-corpus legal accuracy or production readiness.

## Gạch đầu dòng CV — Tiếng Việt

Xây dựng và đánh giá có provenance pipeline Vietnamese Legal RAG
Vertex/Qdrant v3 trên 50 câu hỏi. Retrieval audit chấm 40 case có required
evidence đã xác minh, đạt Document Recall@3 **53/53**, Article Recall@3
**30/30**, Clause Recall@3 **13/14**, all-required **39/40** và không có lỗi kỹ
thuật retrieval/reranker. Answer audit hoàn tất 50/50 generation và guardrail
check; Ragas chấm 49/50 với một lỗi judge có kiểu. Deterministic token F1 chỉ
**0,230**; đây là bằng chứng lát cắt,
không phải độ chính xác pháp lý toàn corpus hoặc production readiness.

## Current evidence boundary

- Dataset: Golden-50 v3, 26 factoid + 24 multi-hop. Retrieval metrics score 40
  cases with 53 verified evidence items and skip 10 as
  `no_verified_gold_label`; generation, guardrails, answer metrics, latency,
  and optional Ragas use all 50.
- Retrieval: Document Recall@1 macro/micro `0.9750 / 0.9623`; Document,
  Article, and Clause Recall@3 `1.0000 / 1.0000 / 0.9231` macro; exact legal
  reference hit `40/40`; all-required coverage `39/40`; no-candidate,
  retrieval-error, and reranker-error rates all `0.0000`.
- Deterministic answer metrics: exact match `0.0000`, token F1 `0.2304`,
  character F1 `0.2226`, ROUGE-L `0.2176`, CHRF `0.3771`, citation precision
  `0.9470`, and invalid citation rate `0.0530`.
- Citation recall and citation coverage are each `1.0000` on only one applicable
  case (`1/50` coverage); do not present them as 50-case citation recall.
- Opt-in Ragas: Faithfulness `0.8887`, Answer Accuracy `0.9184`, Context
  Precision `0.8878`, and Context Recall `0.9354`, with 49/50 coverage and one
  typed Vertex judge error on `case_037`.
- Generation and the observed Ragas judge both used Google Vertex AI
  `gemini-3.5-flash`. The judge is therefore not independent legal review and
  its means do not override deterministic answer metrics.
- Response categories were 49 `disclaimer` and one `mixed_claim_refusal`; all
  50 dataset cases are labelled answerable.
- Automated verification after the stable deployment source state:
  `921 passed, 2 skipped`; 10 deprecation warnings.
- Direct Vercel FastAPI/Jinja SSR at
  <https://vietlex-legal-rag.vercel.app> loaded the SSR root, reported ready,
  returned Supabase-backed search results, and rendered a full legal document.
  Direct `/healthz` was blocked by the browser client and is not claimed.
  Deployment success is not an answer-quality gate.
- Qdrant v3 contains 51,801 points over exactly 4,969 audited document IDs. It
  is not the pinned 518,255-document corpus.
- The retrieval manifest records a clean state at Git `73cd7ca`. The answer
  manifest records `git_dirty=true` because the new retrieval artifact was an
  untracked bound input; both record the same source-state hash and provenance
  status `ok`.

## Immutable current sources

- Retrieval report:
  `docs/evaluation/runs/retrieval-v3-golden50-production-20260902/report.md`
  — SHA-256 `91fc18d0bb9758d81c7b488b0fee518623781a3e8542dca29308167728240662`.
- Retrieval manifest:
  `docs/evaluation/runs/retrieval-v3-golden50-production-20260902/manifest.json`
  — SHA-256 `bea013a3d6cd98f715da09fcc9d36fdeede15a383ff30945d624528b43e439a9`.
- Answer report:
  `docs/evaluation/runs/answer-v3-golden50-production-20260902/report.md`
  — SHA-256 `05ecccbc7f537dd2819ed6114d41662a3293c10f7d6001419d976a52387c7293`.
- Answer manifest:
  `docs/evaluation/runs/answer-v3-golden50-production-20260902/manifest.json`
  — SHA-256 `7ba784fc60d75469bbf0729baa2d40230646db0f2495b93b454f6777f6eef16e`.
- Dataset contract: `docs/evaluation/golden50-v3/manifest.json`; dataset
  SHA-256 `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`.

The 2026-08-27 recheck and Representative-10 artifacts remain immutable
historical evidence. They are useful comparisons but no longer supply the
headline “current” metrics.
