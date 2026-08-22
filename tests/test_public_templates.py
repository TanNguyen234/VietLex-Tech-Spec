from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_index_uses_local_assets_and_exposes_accessible_controls() -> None:
    html = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")

    assert "https://cdn.tailwindcss.com" not in html
    assert "https://unpkg.com" not in html
    assert "https://cdn.jsdelivr.net" not in html
    assert "fonts.googleapis.com" not in html
    assert 'href="/static/css/vietlex.css"' in html
    assert 'src="/static/js/vietlex.js"' in html
    assert 'aria-label="Tìm hội thoại"' in html
    assert 'name="nemo_enabled"' in html
    assert 'id="system-readiness"' in html
    assert 'id="theme-toggle"' in html


def test_message_template_has_visible_actions_and_honest_source_copy() -> None:
    html = (ROOT / "app/templates/chat_message.html").read_text(encoding="utf-8")

    assert "Tài liệu tham chiếu (Qdrant)" not in html
    assert "Nguồn pháp lý truy xuất" in html
    assert 'data-action="copy-answer"' in html
    assert 'data-action="retry"' in html
    assert 'data-action="evaluate"' in html
    assert 'name="csrf_token"' in html
    assert "evidence_views" in html


def test_local_css_covers_focus_touch_and_reduced_motion() -> None:
    css = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "app/static/css/vietlex.css",
            ROOT / "app/static/css/vietlex-enhancements.css",
        )
    )

    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (max-width:" in css and "760px" in css
    assert "--color-accent" in css


def test_evaluation_ui_names_code_metrics_and_handles_ragas_na() -> None:
    script = (ROOT / "app/static/js/vietlex.js").read_text(encoding="utf-8")

    assert "Code evaluation — deterministic" in script
    assert "Không có điểm Ragas" in script
    assert "reason_not_applicable" in script
    assert "timings" in script


def test_markdown_and_typography_support_legal_answer_structure() -> None:
    script = (ROOT / "app/static/js/vietlex.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/vietlex-enhancements.css").read_text(
        encoding="utf-8"
    )

    assert "renderInlineMarkdown" in script
    assert "ordered-list" in script
    assert ".answer-text h3" in css
    assert ".answer-text ol" in css
    assert ".streaming-cursor" in css


def test_chat_ui_exposes_live_pipeline_progress() -> None:
    html = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/vietlex.js").read_text(encoding="utf-8")

    assert 'id="pipeline-progress"' in html
    assert "/api/progress/" in script
    assert "request_id" in script
