# Serverless completion — 2026-09-09

Runtime scope: bounded opt-in PDF OCR, serverless guardrail self-check, Groq primary availability repair. Admin and Mongo originals were delivered separately in 62fbec7; see [admin verification](admin-storage-20260909/README.md).

## Verification

- Provider-free full suite: **1,233 passed, 4 live tests deselected, 30 warnings, 206.25 seconds**. Warnings are existing deprecations. Ruff, repository artifact check and diff whitespace check passed.
- Focused initial runtime gate: 144 passed. Live-derived parser/catalog regression: intended RED 3 failed/25 passed, then GREEN 42 passed. Only an extra trailing blank line in the prompt constants was removed after the full suite; the prompt parity test was rerun. No behavior changed.
- Two image-only PDF transcriptions preserved Vietnamese accents, date `15/09/2026` and amount `1200000`: **2/2 samples**, all pages represented. This is a small functional sample, not an OCR quality corpus.
- Guardrails: initial exact-token parser allowed 2/4 cases and correctly reported 2 technical parsing failures. Two diagnostic calls showed the exact prompt label preceding `no`; parser now allows only that exact optional label. Rechecks passed **2/2**, covering input allow and output rejection. Other initial cases covered off-topic input rejection and supported output. No technical failure was relabeled as hallucination.
- Groq identical-input A/B: old alias 0/2 available (HTTP 404); `qwen/qwen3.8-27b` **2/2 exact JSON**, coverage 2/2, skipped 0. Primary updated; fallback order and alias identifiers retained for compatibility. This establishes synthetic operational availability, not legal quality.
- NVIDIA identical-input A/B: original 0/2 (HTTP 410), candidate `mistralai/mistral-large-2-instruct` 0/2 (HTTP 404). Candidate **not promoted**. No successful NVIDIA generation or legal comparison claimed.
- Real local service calls: selected-evidence answer returned the expected date and reference; obligation matrix returned both obligations with references; claim verification assessed **1/1**, supported with exact quote, skipped 0. Three services returned valid contracts, **3/3**. Browser integration for these three actions in this follow-on slice: **NOT RUN**.
- Model comparison exercised exact adapters with same-input hash: Groq returned an answer/224 reported tokens, NVIDIA unavailable. Overall comparison remains partial; Groq adapter did not report observed model identity, so identity is **not verified** by this service result (raw A/B endpoint did report identity).

## Calls and evidence limits

User approved at most 24 additional generation attempts without automatic retries. Consumed before deployment: A/B 8 + OCR/initial guardrails 6 + guard diagnosis 2 + corrected guardrails 2 + selected/obligations/claims 3 + exact model comparison 2 = **23**. One remaining attempt is reserved for production OCR. HTTP 404/410 attempts count against the allowance; no billing cost inferred. No new RAG benchmark or retrieval call occurred.

[Raw results, exact scripts, hashes and source snapshot](runtime-completion-20260909/manifest.json) accompany this report. Scripts used real configured providers. The feature harness only forced transport retries to zero and disabled fallback; it supplied no fake model responses. The initial console failed to print Unicode after persisting OCR result; continuation skipped every previously attempted case. PDF generation timestamps changed during continuation, so the first OCR fixture cannot be byte-reproduced from the current generated file. The source snapshot was captured after probes/fixes; these artifacts are **not a contemporaneous clean-tree benchmark**.

## Commands and files

[Changed files](runtime-completion-20260909/changed-files.txt). PowerShell from repository root, Python 3.12 project venv:

```powershell
.venv/Scripts/python.exe -m pytest tests/services/test_workspace_ocr.py tests/services/test_workspace_documents.py tests/services/test_vertex_ai.py tests/services/test_serverless_guardrails.py tests/services/test_direct_llm.py tests/test_workspace_routes.py tests/test_api_routes.py tests/test_database.py tests/test_admin_navigation.py tests/test_public_templates.py tests/test_deployment_contract.py -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-runtime-completion-focused'
.venv/Scripts/python.exe -m pytest tests/services/test_serverless_guardrails.py tests/evaluation/test_provenance.py tests/services/test_model_comparison.py tests/services/test_direct_llm.py -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-guard-catalog-green'
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest tests -q -m 'not live' --durations=10 --junitxml=output/verification-runtime-completion-20260909-tests.xml -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/08/01a081ac-2897-7a21-a24b-71ee2809f0c7/pytest-runtime-completion-final'
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe scripts/check_repository_artifacts.py
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
.venv/Scripts/python.exe output/live-completion-ab.py
.venv/Scripts/python.exe output/live-completion-vertex.py
.venv/Scripts/python.exe output/live-guard-diagnosis.py
.venv/Scripts/python.exe output/live-guard-fixed.py
.venv/Scripts/python.exe output/live-completion-features.py
```

Do not blindly rerun live scripts: the allowance is finite and each journal refuses or skips prior attempts.

## Remaining acceptance and remote effects

Two-user/mail acceptance awaits the user's registration/verification of the second identity; protected admin remains unchanged. NVIDIA availability needs a working authorized model/endpoint. Previously observed Logfire export HTTP 401 still requires owner credential remediation. Large-document processing beyond five-page OCR, backup restore/load/security testing and expert legal benchmark acceptance are **NOT RUN**. Historical answer baseline failed; corpus coverage remains 14,962 audited v3 documents. No production-ready claim.

No corpus ingestion, vector migration/deletion, credential change, new storage service or account mutation. Synthetic originals remain in the existing expiring workspace. Unrelated skill/config/build/evaluation directories remain untouched; Git tree is intentionally dirty. Follow-on commit/CI/deployment and final production OCR evidence will be recorded after delivery.
