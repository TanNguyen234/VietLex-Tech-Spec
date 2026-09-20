# DOCX source links — 20/09/2026

Scope: citation IDs in report body link to saved evidence snapshots inside DOCX. Each validated source HTTP(S) URL is a separate external hyperlink; query and fragment are preserved. Unknown/duplicate IDs stay text. User-written Markdown links are not activated. This does not infer an article URL when the saved source has none.

TDD: two intended failures (missing relationships) → 6 focused tests passed. Ruff and focused git diff check passed. Full suite: **1.365 passed, 4 skipped, 30 warnings**, 460,03 seconds. Four skipped live tests are not counted as verified. Tests use synthetic adversarial data separately from the live export below.

Actual saved public-law report from Mongo, local HTTP export 200/no-store: 3 bookmarks, 6 citation links, 3 external links, all anchors resolve. Bundled python-docx reopened the downloaded DOCX: 56 paragraphs, 9 hyperlinks. The application's venv lacks python-docx; first independent-parser attempt failed ModuleNotFoundError, then used the existing bundled document runtime. No production dependency was added. Microsoft Word UI NOT RUN; production export pending deployment.

Commands:
- `.venv/Scripts/python.exe -m pytest tests/test_report_deliverables.py -q`
- `.venv/Scripts/python.exe -m ruff check app/services/report_deliverables.py tests/test_report_deliverables.py`
- `.venv/Scripts/python.exe -m pytest -q --junitxml=tmp/continuation-20260920/docx-full.xml`
- `.venv/Scripts/python.exe tmp/continuation-20260920/docx_live.py`

Source: [Microsoft Wordprocessing Hyperlink](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.hyperlink), [BookmarkStart](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.bookmarkstart).

Changed runtime: `app/services/report_deliverables.py`; tests: `tests/test_report_deliverables.py`. No provider, credential, schema or data mutation for export. Unrelated working-tree changes are preserved.
