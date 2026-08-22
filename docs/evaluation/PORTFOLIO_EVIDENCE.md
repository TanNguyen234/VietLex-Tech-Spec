# VietLex CV / Portfolio Evidence

## CV bullet — English

Built and empirically evaluated a Vietnamese legal RAG pipeline on 50 deterministic QA cases (26 factoid, 24 multi-hop), achieving Ragas Faithfulness **0.916**, Answer Accuracy **0.895**, Context Precision **0.876**, and Context Recall **0.933**, with **50/50** completed generations, **50/50** NeMo guardrail passes, full Ragas coverage, and zero technical errors. The retrieval audit used 40 cases with fully verified required evidence and reached macro Document Recall@3 **0.925** (`50/53` evidence items by micro recall).

## Gạch đầu dòng CV — Tiếng Việt

Xây dựng và đánh giá thực nghiệm hệ thống Vietnamese Legal RAG trên 50 câu hỏi xác định (26 factoid, 24 multi-hop), đạt Ragas Faithfulness **0,916**, Answer Accuracy **0,895**, Context Precision **0,876** và Context Recall **0,933**; **50/50** câu sinh hoàn chỉnh, **50/50** vượt NeMo guardrail, Ragas đủ 50/50 và không có lỗi kỹ thuật. Phần retrieval được kiểm chứng trên 40 case có toàn bộ required evidence đã xác minh, đạt Document Recall@3 macro **0,925** và micro `50/53`.

## Evidence boundary

- Exact Balanced-50 Ragas means: Faithfulness `0.9158`, Answer Accuracy `0.8950`, Context Precision `0.8757`, and Context Recall `0.9333`.
- Representative-10 is fully `all-required-verified`: Ragas coverage `10/10`, Faithfulness `0.9857`, Answer Accuracy `0.9750`, Context Precision `0.9400`, Context Recall `1.0000`, and zero technical errors.
- Balanced-50 contains all 40 fully verified cases plus 10 deterministic reference-only cases. Ragas, generation, and guardrails use all 50; verified retrieval metrics use the 40-case denominator.
- Balanced-50 case-list SHA-256: `56ae294f9698569ab4f7ae11ed87aabfa7c79b616919378dc0f5d4e32e53bdf3`.
- Balanced-50 report SHA-256: `9b077dc5acb1ddd8fd40089e1030c1a98638760a676fcf698c3eef2db9df3c99`.
- Representative-10 report SHA-256: `0e3340af2ea6b3e8b6f344d66e71c704abebd08ffb35d8a8dc80a2c376fd64ce`.
- Judge: Google Vertex AI `gemini-3.5-flash`; thinking level: `MINIMAL`; NeMo mode: `enforce`; rewrite: `off`.
- Automated verification before the final live run: `762 passed, 2 skipped`; four deprecation warnings; `git diff --check` passed.
- These results demonstrate a bounded evaluation slice, not production readiness, whole-corpus legal accuracy, or independent legal review.

## Immutable sources

- `docs/evaluation/runs/answer-representative10-v6-live-20260822/report.md`
- `docs/evaluation/runs/answer-representative10-v6-live-20260822/manifest.json`
- `docs/evaluation/runs/answer-representative10-v6-live-20260822/answer_results.json`
- `docs/evaluation/runs/answer-balanced50-v2-live-20260822/report.md`
- `docs/evaluation/runs/answer-balanced50-v2-live-20260822/manifest.json`
- `docs/evaluation/runs/answer-balanced50-v2-live-20260822/answer_results.json`
