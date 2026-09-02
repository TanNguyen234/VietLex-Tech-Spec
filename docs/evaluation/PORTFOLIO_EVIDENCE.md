# VietLex CV / Portfolio Evidence

Current evidence date: 2026-09-01.

## CV bullet — English

Built and reproducibly evaluated a Vertex/Qdrant v3 Vietnamese legal RAG
pipeline on 50 QA cases. The retrieval audit scored 40 cases with verified
required evidence and achieved Document Recall@3 **53/53**, Article Recall@3
**30/30**, Clause Recall@3 **13/14**, all-required coverage **39/40**, and zero
retrieval/reranker technical errors. The separate answer audit completed 50/50
generations and guardrail checks with zero technical errors; deterministic
token F1 remained **0.234**, so the result is reported as bounded evidence, not
whole-corpus legal accuracy or production readiness.

## Gạch đầu dòng CV — Tiếng Việt

Xây dựng và đánh giá có provenance pipeline Vietnamese Legal RAG
Vertex/Qdrant v3 trên 50 câu hỏi. Retrieval audit chấm 40 case có required
evidence đã xác minh, đạt Document Recall@3 **53/53**, Article Recall@3
**30/30**, Clause Recall@3 **13/14**, all-required **39/40** và không có lỗi kỹ
thuật retrieval/reranker. Answer audit hoàn tất 50/50 generation và guardrail
check, nhưng deterministic token F1 chỉ **0,234**; đây là bằng chứng lát cắt,
không phải độ chính xác pháp lý toàn corpus hoặc production readiness.

## Current evidence boundary

- Dataset: Golden-50 v3, 26 factoid + 24 multi-hop. Retrieval metrics score 40
  cases with 53 verified evidence items and skip 10 as
  `no_verified_gold_label`; generation, guardrails, answer metrics, latency,
  and optional Ragas use all 50.
- Retrieval: Document Recall@1 macro/micro `0.9500 / 0.9245`; Document,
  Article, and Clause Recall@3 `1.0000 / 1.0000 / 0.9231` macro; exact legal
  reference hit `40/40`; all-required coverage `39/40`; no-candidate,
  retrieval-error, and reranker-error rates all `0.0000`.
- Deterministic answer metrics: exact match `0.0000`, token F1 `0.2336`,
  character F1 `0.2250`, ROUGE-L `0.2210`, CHRF `0.3796`, citation precision
  `0.9567`, and invalid citation rate `0.0433`.
- Citation recall and citation coverage are each `1.0000` on only one applicable
  case (`1/50` coverage); do not present them as 50-case citation recall.
- Opt-in Ragas: Faithfulness `0.9197`, Answer Accuracy `0.9150`, Context
  Precision `0.8733`, and Context Recall `0.9367`, with 50/50 coverage and zero
  judge technical errors.
- Generation and the observed Ragas judge both used Google Vertex AI
  `gemini-3.5-flash`. The judge is therefore not independent legal review and
  its means do not override deterministic answer metrics.
- Response categories were 49 `disclaimer` and one `mixed_claim_refusal`; all
  50 dataset cases are labelled answerable.
- Automated verification after the stable deployment source state:
  `917 passed, 2 skipped`; 10 deprecation warnings.
- Direct Vercel FastAPI/Jinja SSR at
  <https://vietlex-legal-rag.vercel.app> passed health, readiness, root, and a
  CSRF-protected chat smoke request. Deployment success is not an answer-quality
  gate.
- Qdrant v3 contains 51,801 points over exactly 4,969 audited document IDs. It
  is not the pinned 518,255-document corpus.
- Both current manifests record `git_dirty=true`, provenance status `ok`, the
  dirty diff hash, and source-state hash. They are not reproducible from the Git
  commit SHA alone.

## Immutable current sources

- Retrieval report:
  `docs/evaluation/runs/retrieval-v3-golden50-online-vercel-20260901/report.md`
  — SHA-256 `f4b1f1a411e5f90273f6b8b47508630b7a73834695e4c75a48701c7ae54610a6`.
- Retrieval manifest:
  `docs/evaluation/runs/retrieval-v3-golden50-online-vercel-20260901/manifest.json`
  — SHA-256 `b6533bd51a25bc857d6e01fcec4ca4a134f651abbee747314758e4ac9cd27eb2`.
- Answer report:
  `docs/evaluation/runs/answer-v3-golden50-online-vercel-20260901/report.md`
  — SHA-256 `a43772cbdd7fe1b7b54da28df7f76757e800527d1fdafb04deac46b77936ac58`.
- Answer manifest:
  `docs/evaluation/runs/answer-v3-golden50-online-vercel-20260901/manifest.json`
  — SHA-256 `e53ef8bff24f7cedf1c14c378845ec02dc4bc0393b35b2b9db8dc8fefa34f8ad`.
- Dataset contract: `docs/evaluation/golden50-v3/manifest.json`; dataset
  SHA-256 `caa3fc19cd22bcce4b87e96adf13544d0c3cc174cca2d0e365a848e0da9a981f`.

The 2026-08-27 recheck and Representative-10 artifacts remain immutable
historical evidence. They are useful comparisons but no longer supply the
headline “current” metrics.
