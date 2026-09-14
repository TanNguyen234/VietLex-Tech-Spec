# OCR output contract

Scope: app/services/workspace_ocr.py, app/services/vertex_ai.py and focused tests. Authorization: real provider calls, fixes, commit/push/deploy. No provider/model change, no index change.

Evidence: production read 502 ocr_invalid_response; identical local one-page request returned the schema object ($defs/properties) rather than pages, STOP, 781 prompt tokens / 265 output tokens. Provider event incorrectly success=true before parse. Raw public-source diagnostic is in tmp/data-integrity-20260913/ocr-single-page-baseline.json.

- [x] RED pure tests for request/schema separation and parser rejecting schema echo, incomplete output and wrong page coverage.
- [x] Add optional response_json_schema to Vertex.generate configuration; other callers retain default None. OCR prompt only describes transcription; JSON schema goes through transport and fixes exact page count.
- [x] Move provider event emission after OCR parsing and empty-result validation, preserving usage counts on invalid output. Add focused regression using existing unit harness; live proof remains separate.
- [x] Run identical one-page public PDF after fix, record bytes SHA, output, validation, provider usage. No mock in live baseline/treatment.
- [x] Full suite after stable diff, production retry on the same test workspace, publish failures and successes separately, split commits/push.

Official SDK: https://github.com/googleapis/python-genai — GenerateContentConfig.response_json_schema. Installed SDK introspection confirms field exists. Validation still required; structured output is not OCR/legal accuracy certification.
