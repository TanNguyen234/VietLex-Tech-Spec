# Retained-source analysis

Runtime addition, separate from selected-evidence analysis. Explicit user action analyzes all retained readable pages of one exact URL/document hash, ordered by page. It never fetches more pages or merges versions, and never silently truncates beyond 120,000 characters / 24,000 whitespace words. Missing pages and OCR limits stay visible. Provider/model unchanged.

TDD targets: version isolation, latest-page selection, oversize rejection, exact quote/page validation and ownership/CSRF/quota route integration. UI action belongs in source library; response keeps source coverage and inspectable quotes. No legal-effect promotion. Full real 10-case acceptance after source stability; model status is not legal correctness. Preserve raw results, input hashes, config/git manifest and command before execution.
