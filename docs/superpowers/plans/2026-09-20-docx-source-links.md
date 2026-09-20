# DOCX source links implementation plan

Goal: exported reports let readers follow known citation IDs to saved source excerpts and open validated HTTP(S) original URLs.
Architecture: extend the existing provider-free OOXML writer; no dependencies, provider, database or configuration changes. Preserve report text and source snapshots. Unknown IDs remain text. Never activate user-written Markdown URLs.
Authority: user requested complete report deliverables and commits/push. Runtime change limited to report_docx and tests.

- [x] RED: parse DOCX XML, assert every known citation targets a real unique bookmark; external relationships preserve URL fragment/query; unsafe URLs remain inactive; XML control characters cannot corrupt output.
- [x] Implement in app/services/report_deliverables.py. Review all callers (research_report_routes export only), encoding, duplicate IDs and error paths.
- [x] Focused tests tests/test_report_deliverables.py; stable diff review, broader suite; export actual stored public-law report and inspect via document parser. Word UI validation NOT RUN unless available.
- [ ] Update FEATURE_STATUS and evidence after stable checks; commit, push and production export verification.

Reference: https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.hyperlink and bookmarkstart (OOXML anchors/relationships).
