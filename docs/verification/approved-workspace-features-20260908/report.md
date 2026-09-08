# Approved workspace features: verification, 2026-09-08

This is implementation/test evidence, not a legal-quality benchmark or production-readiness claim.

## Result

The final whole suite returned **1163 passed, 4 failed, 2 skipped**, 20 warnings, 1071.59 seconds. All four failed cases then passed together in **18.90 seconds**, with unchanged source and timeout limits. Do not describe the whole-suite invocation as an all-pass run.

Three failures were subprocess timeouts (document parser, application import, evaluation CLI help). The provenance case used a temporary directory underneath the repository, so Git discovered its parent repository. The isolated rerun placed temporary files outside the checkout and retained the forward-slash Git safe-directory setting.

An earlier whole suite returned 1166 passed, 1 failed, 2 skipped (913.60 seconds); its Git check-attr process lacked the effective safe-directory setting. That single case passed after correcting the test-process Git environment. A trailing space in research-workspace.js was removed before the final whole suite. The pre-final focused integration group passed 71 tests. Ruff and Node syntax checks passed; git diff --check passed after whitespace cleanup. No behavior source changed after the final whole suite.

## Exact final commands

```powershell

$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=output/pytest-feature-full-final-20260908-c82f3

.venv/Scripts/python.exe -m pytest tests/evaluation/test_provenance.py::test_non_git_directory_is_typed_unavailable tests/services/test_document_worker.py::test_isolated_extraction_returns_text_and_typed_errors tests/test_deployment_contract.py::test_web_import_does_not_eagerly_load_ai_runtime tests/test_run_eval_suite.py::test_help_does_not_boot_the_full_rag_application -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697/pytest-feature-final-recheck-20260908-a93f'

.venv/Scripts/python.exe -m ruff check app tests
node --check app/static/js/research-workspace.js
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check

```

## Delivered scope and remaining work

- F01: bounded model claim assessment with server-validated exact quotes; no expert legal certification.
- F02: human-admin-reviewed dated official-source effect records; no comprehensive automatic amendment graph.
- F03: bounded reader for two approved official HTML origins, duplicate/conflict indications and exact-excerpt pinning; general web/PDF coverage remains incomplete.
- F04: selected-evidence structured report plus atomic claim assessment; not autonomous comprehensive research.
- F05: OCR and large-object storage remain unimplemented.
- F06: deterministic two-document redline and explicit bounded full-document review batches, with persistent progress and private-document deletion guards.
- F07: explicit-date timeline; relative legal deadlines remain unresolved.
- F08: two configured model adapters, identical inputs and independent observed usage/errors; missing model identity remains partial/unobserved.
- F09: remaining attempt quotas and process-local admission counters; actual billing and complete embedding/reranker/retry accounting remain unavailable.
- F10: no corpus expansion, new legal gold certification, paid A/B or live benchmark performed.

## Review and operational limits

The stable feature diff received cross-review across the existing bounded agents and root source review. Findings addressed exact quote membership, privacy/no-store, immutable provenance, model identity, report claim-source alignment, Mongo pipeline literal handling and progress retention independent of rotating history. A separate new Sol reviewer was unavailable due the session agent limit; this is not claimed as a Sol review.

Unit and mocked integration tests do not prove live model, real Mongo aggregation, authenticated reviewer, SMTP or edge-WAF behavior. These are NOT RUN / UNVERIFIED. No production credentials, vector stores or paid-provider budgets were changed. Demo commit 4e6a4d2 was previously deployed successfully; this report is generated before deployment of the new feature commits.

The manifest lists changed paths, source hashes and dirty-tree proof. Unrelated local config, old evaluation directories and generated packaging directories are excluded from the feature commits.
