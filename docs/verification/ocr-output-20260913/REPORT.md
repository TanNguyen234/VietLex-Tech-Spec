# OCR structured output: observed production failure and fix

Runtime commit `f1a1b2d` was pushed and deployed to production as `dpl_EoXcRf4NroHzcxEScX3esUJYFQCR`. Production domain promotion succeeded. These checks apply to that runtime, not uncommitted later work.

## Observed defect

A real official one-page PDF request failed twice on production with HTTP 502 / ocr_invalid_response. The provider emitted a schema object instead of the requested pages. A local reproduction on the exact one-page PDF also returned the schema, STOP, with 781 prompt / 265 output tokens. The operation incorrectly recorded provider success before validating output. The retained pre-fix response shows that misleading success event.

The fix separates transcription instructions from native response_json_schema configuration, enforces the exact requested page count and preserves strict parsing. Provider success is emitted after parsing and extraction checks; invalid results retain usage counts while marking failure.

## Evidence

- Identical public PDF SHA-256: `a0f81fe66e2e1ab42c33ffdda4e853462badbef7f2fd04508643b6dde52d4df4`.
- Local real Vertex A/B: baseline invalid schema echo; treatment valid 1 page / 1,978 characters, STOP, 805 prompt / 644 output tokens. Same provider/model, PDF bytes, output budget and thinking level. Prompt and structured configuration changed.
- Production after deployment: workspace GET 200; official PDF OCR 200; pin 200; duplicate pin 409; saved source GET 200 and Cache-Control no-store. Actual evidence ID matched the URL + PDF-version + quote contract.
- Production OCR event: google_vertex_ai / gemini-3.5-flash, success true, 805 prompt / 652 output / 1,457 total tokens. The response carries unverified legal status.
- Automated suite: **1,287 passed, 30 warnings**, 340.92 seconds. Command and full raw log retained locally; hashes are published. Integration/visual directories excluded. Unit test doubles are not live-provider proof.

## Limits

This fixes one observed output-structure failure; it does not certify every PDF, transcription accuracy, legal correctness or global production reliability. The ten-document/178-page reading run used the earlier OCR request and is reported separately. Existing deprecation warnings and Logfire authentication failure are not fixed here. No index, credential, legal-status promotion or model migration was performed.

The production summary's real_provider/real_model fields are null because its harness read the wrong response keys. The actual provider/model are present in the locally retained response's provider_calls and source ocr_provider/ocr_model fields; the manifest records the observed events without rewriting the original summary.

Native schema support: [official Python GenAI SDK](https://github.com/googleapis/python-genai). Source blob hashes in the manifest use Git bytes; Windows deployment archives may use CRLF.

## Publication boundary

Raw response, model output, logs and diagnostic runners referenced above are retained locally; they are not published in this commit. The manifest records their hashes for local verification. Published evidence is limited to this curated report, aggregate results where present and public-source references. Production workspace identifiers and cookie values are excluded. This restricts public reproducibility; it does not turn summaries into raw evidence.
