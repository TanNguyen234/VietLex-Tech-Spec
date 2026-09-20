# Ten original questions — analysis of retained official sources

This is a live service/provider verification run, not certification that ten legal answers are correct. Vertex `gemini-3.5-flash`, MINIMAL, 4,096 output tokens; source/context contract changed from selected excerpts to one full retained source version. It is not an identical-context model A/B.

## Results

- 10/10 service responses valid; 9 `ok`, 1 `insufficient_evidence` after enforcing unanswered parts.
- 142 selected IDs exist: 134 original retained page passages and 8 separately labelled official-page metadata records. Membership is not semantic citation precision.
- 178/178 retained PDF pages supplied; OCR accuracy, seals, handwritten fields and annex interpretation are not certified.
- All ten document numbers absent from the 518,255-document local metadata store and 4,969-document local v3 store (NFC/whitespace/casefold comparison). Remote database absence is NOT RUN.
- Agriculture still asks for the old text of repealed provisions; a useful new-law summary is not a full old/new comparison.

| Case | Pages | Status | References | Seconds |
|---|---:|---|---:|---:|
| agriculture | 24 | insufficient_evidence | 35 | 13.45 |
| aviation | 4 | ok | 8 | 4.69 |
| credit | 4 | ok | 8 | 5.27 |
| electricity | 18 | ok | 12 | 5.52 |
| health | 6 | ok | 14 | 11.22 |
| imports | 39 | ok | 6 | 5.64 |
| maritime | 17 | ok | 8 | 4.53 |
| procurement | 23 | ok | 14 | 4.97 |
| reserves | 40 | ok | 29 | 7.27 |
| resources_tax | 3 | ok | 8 | 6.47 |

## What the investigation changed

The original selected-context baseline remained 2/10 `ok` and 8/10 insufficient. A facts-first prompt variant on the same ten inputs produced 0/10 `ok` and was rejected. Grouping complete retained pages helped, but asking the model to retype quotations introduced exact-text failures. The final service sends server-generated passage IDs and resolves selected IDs back to original text. Official metadata has its own labelled citation because an OCR header can miss a document number/date that the portal actually provides.

Earlier 20-reference limits rejected a real 32-reference response; the bounded limit is now 64. One pre-final reserves call timed out at the test harness 180-second deadline and succeeded on an unchanged retry. Those exploratory failures are not erased by this final run. Final captured responses all completed successfully.

The aviation portal explicitly lists 68/2026/TT-BXD, issued 10-09-2026, effective 01-01-2027. The earlier generated answer incorrectly treated missing OCR header fields as missing source information; the final answer uses the portal metadata. [Official record](https://vanban.chinhphu.vn/?pageid=27160&docid=219442).

## Reproducibility and limits

Execution manifest was written before provider calls and includes dirty-tree diff SHA-256, relevant source hashes, configuration fingerprint, and original captured input hashes. Input files preserve the exact ten questions and captured real source text. Raw model responses and validated outputs are separate in each result. No mocked provider responses, judge calls or fabricated source content. `run_capture.py` records how this local run was executed; it references ignored original capture paths and is not a standalone downloadable corpus.

The UI/API smoke is separate from this direct service run. SDK internal retries and monetary cost are not inferred from token counts. The metric file names unexecuted legal/retrieval metrics explicitly instead of assigning a score. Registry history remains human-reviewed and independent of model answers.
