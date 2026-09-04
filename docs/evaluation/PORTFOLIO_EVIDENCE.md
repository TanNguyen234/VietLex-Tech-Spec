# VietLex CV / Portfolio Evidence

Current evidence date: 2026-09-03.

## CV bullet — English

Built and reproducibly evaluated a Vertex/Qdrant v3 Vietnamese legal RAG
pipeline on 50 QA cases. The retrieval audit scored 40 cases with verified
required evidence and achieved Document Recall@3 **53/53**, Article Recall@3
**29/30**, Clause Recall@3 **13/14**, all-required coverage **39/40**, and zero
retrieval/reranker technical errors. The separate answer audit completed 50/50
generations, guardrail checks, and Ragas scores with zero technical errors.
Deterministic token F1 remained **0.230**, so the result is bounded evidence, not
whole-corpus legal accuracy or production readiness.

## Gạch đầu dòng CV — Tiếng Việt

Xây dựng và đánh giá có provenance pipeline Vietnamese Legal RAG
Vertex/Qdrant v3 trên 50 câu hỏi. Retrieval audit chấm 40 case có required
evidence đã xác minh, đạt Document Recall@3 **53/53**, Article Recall@3
**29/30**, Clause Recall@3 **13/14**, all-required **39/40** và không có lỗi kỹ
thuật retrieval/reranker. Answer audit hoàn tất 50/50 generation và guardrail
check; Ragas chấm 50/50 không có lỗi kỹ thuật. Deterministic token F1 chỉ
**0,230**; đây là bằng chứng lát cắt,
không phải độ chính xác pháp lý toàn corpus hoặc production readiness.

## Current evidence boundary

- Dataset: Golden-50 v3, 26 factoid + 24 multi-hop. Retrieval metrics score 40
  cases with 53 verified evidence items and skip 10 as
  `no_verified_gold_label`; generation, guardrails, answer metrics, latency,
  and optional Ragas use all 50.
- Retrieval: Document Recall@1 macro/micro `0.9000 / 0.8679`; Document,
  Article, and Clause Recall@3 `1.0000 / 0.9630 / 0.9231` macro; exact legal
  reference hit `40/40`; all-required coverage `39/40`; no-candidate,
  retrieval-error, and reranker-error rates all `0.0000`.
- Deterministic answer metrics: exact match `0.0000`, token F1 `0.2305`,
  character F1 `0.2230`, ROUGE-L `0.2197`, CHRF `0.3765`, citation precision
  `0.9183`, and invalid citation rate `0.0817`.
- Citation recall and citation coverage are each `1.0000` on only one applicable
  case (`1/50` coverage); do not present them as 50-case citation recall.
- Opt-in Ragas: Faithfulness `0.8221`, Answer Accuracy `0.9100`, Context
  Precision `0.8600`, and Context Recall `0.9500`, with 50/50 coverage and zero
  judge technical errors.
- Generation and the observed Ragas judge both used Google Vertex AI
  `gemini-3.5-flash`. The judge is therefore not independent legal review and
  its means do not override deterministic answer metrics.
- Response categories were 49 `disclaimer` and one `mixed_claim_refusal`; all
  50 dataset cases are labelled answerable.
- Automated verification: `925 passed, 2 skipped`; 10 deprecation warnings.
  Two deployment tests timed out under full-suite load and passed independently.
- Direct Vercel FastAPI/Jinja SSR at
  <https://vietlex-legal-rag.vercel.app> loaded the SSR root, reported ready,
  returned Supabase-backed search results, and rendered a full legal document.
  Direct `/healthz` was blocked by the browser client and is not claimed.
  Deployment success is not an answer-quality gate.
- Qdrant v3 contains 141,798 points over exactly 14,962 audited document IDs;
  Supabase contains the matching 14,962 full documents. This
  is not the pinned 518,255-document corpus.
- The 2026-09-03 retrieval and answer manifests bind Git `bf60d29`, record the
  tested dirty source state and exact diff hashes, and have provenance status
  `ok`.

## Immutable current sources

- Retrieval report:
  `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-rrf-dbsf-20260903/report.md`
  — SHA-256 `ea20cdedb72128bab7df5cf83f5beae8611af7f14e0c5bd387821536f8fafd58`.
- Retrieval manifest:
  `docs/evaluation/runs/retrieval-v3-golden50-expanded14962-rrf-dbsf-20260903/manifest.json`
  — SHA-256 `6e63ff87fdba80b61b3de65e38f7b28bbf255bacc3d9111af6fe2044ee1e8d54`.
- Answer report:
  `docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903/report.md`
  — SHA-256 `5c480460f10f985368ca79fa1d6ae4e85253739e6ff548d413a3a1c6fff900a2`.
- Answer manifest:
  `docs/evaluation/runs/answer-v3-golden50-expanded14962-rrf-dbsf-20260903/manifest.json`
  — SHA-256 `42d0af9881a876a3a88609789fc17d5f79458735640083e12fdc9df72af850e7`.
- Dataset contract: `docs/evaluation/golden50-v3/manifest.json`; dataset
  SHA-256 `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`.

The 2026-08-27 recheck and Representative-10 artifacts remain immutable
historical evidence. They are useful comparisons but no longer supply the
headline “current” metrics.
