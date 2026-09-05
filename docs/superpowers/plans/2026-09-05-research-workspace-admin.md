# Research workspace and admin evaluation implementation plan

Goal: apply the supplied product research to the existing workspace and give administrators a complete, artifact-backed evaluation view.

Architecture: reuse FastAPI/Jinja, the evaluation lab projector, and existing research workflows. Preserve v3 and legacy retrieval contracts, authentication and provider-free evaluation. No commits, remote mutations, provider probes, migrations or evidence promotion are authorized.

Classification: runtime presentation, offline evaluation presentation, documentation.

1. Extend `app/services/evaluation_lab.py` to support answer and retrieval artifacts, preserve unavailable metrics, explicit bounded coverage, status distributions, latency summaries and stored quality gates. Add service RED tests in `tests/services/test_evaluation_lab.py`, then implement and run `.venv/Scripts/python.exe -m pytest tests/services/test_evaluation_lab.py -q`.
2. Add authenticated `/admin/evaluations` with a validated local run selector and case drilldown in `app/api/evaluation_lab_routes.py`. Reuse `evaluation_lab.html`; add route tests for authentication, traversal, unavailable artifacts and real metrics. No arbitrary path input or provider calls.
3. Improve shared typography/light theme and workflow launcher through existing CSS/templates. Add an accessible document outline without altering legal source text. Verify document route and public template contracts.
4. Inspect stable source/error paths using OCR delegation file/rule selection and direct source review (CRG unavailable). Run full provider-free pytest once after review is clean.
5. Update current architecture and record exact results, limits, changed files and inherited Git state after verification. Product roadmap features requiring new research providers, ingestion or legal authority verification remain explicitly separate from implemented workflows.

Invariants: missing values are N/A; macro means show observed denominators; truncation is visible; gate status comes only from the stored gate; provenance is reported, never independently certified by the UI; selected runs stay under the local run root; public lab remains pinned; admin uses `require_admin` and no-store responses.
