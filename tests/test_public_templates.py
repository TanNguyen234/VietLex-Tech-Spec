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
    assert 'name="nemo_enabled"' not in html
    assert 'id="system-readiness"' in html
    assert 'id="theme-toggle"' in html
    assert 'href="/workspaces"' in html
    assert 'href="/evaluation-lab"' in html


def test_message_template_has_visible_actions_and_honest_source_copy() -> None:
    html = (ROOT / "app/templates/chat_message.html").read_text(encoding="utf-8")

    assert "Tài liệu tham chiếu (Qdrant)" not in html
    assert "Nguồn pháp lý truy xuất" in html
    assert 'data-action="copy-answer"' in html
    assert 'data-action="retry"' in html
    assert 'data-action="evaluate"' in html
    assert 'name="csrf_token"' in html
    assert "evidence_views" in html
    assert 'href="{{ evidence.source_url }}"' in html
    assert 'href="/documents/{{ evidence.document_id }}"' in html
    assert 'data-action="pin-evidence"' in html
    assert 'data-action="inspect-retrieval"' in html
    assert "Liên kết bằng chứng" in html


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


def test_legal_search_uses_compact_page_specific_typography() -> None:
    html = (ROOT / "app/templates/legal_search.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/vietlex-enhancements.css").read_text(
        encoding="utf-8"
    )

    assert 'class="legal-page legal-search-page"' in html
    assert ".legal-search-page>.welcome-card" in css
    assert ".legal-results h2" in css
    assert "font-size:clamp(1.1rem" in css


def test_workspace_and_evaluation_lab_templates_expose_real_workflows() -> None:
    workspace = (ROOT / "app/templates/research_workspace.html").read_text(encoding="utf-8")
    lab = (ROOT / "app/templates/evaluation_lab.html").read_text(encoding="utf-8")
    document = (ROOT / "app/templates/legal_document.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/research-workspace.js").read_text(encoding="utf-8")

    assert "Phạm vi bằng chứng" in workspace
    assert "/analyses/selected" in workspace
    assert "/analyses/compare" in workspace
    assert "/analyses/obligations" in workspace
    assert "/research/plan" in workspace
    assert "official_research_enabled" in workspace
    assert "Mở trang này không chạy đánh giá mới." in lab
    assert "Git dirty" in lab
    assert "Trợ lý nghiên cứu" in document
    assert "evidenceGroup" in script
    assert "change_type" in script
    assert "modality" in script
    assert "source.snippet" in script
    assert "data-research-plan" in script
    assert 'enctype="multipart/form-data"' in workspace
    assert "workspace.documents" in workspace
    assert "data-document-clause" in workspace
    assert "data-contract-review" in workspace
    assert "contract_review" in script
    assert "legal_evidence_ids" in script


def test_product_forms_and_navigation_are_usable_without_chat_script() -> None:
    nav = (ROOT / "app/templates/product_nav.html").read_text(encoding="utf-8")
    admin = (ROOT / "app/templates/admin.html").read_text(encoding="utf-8")
    workspace = (ROOT / "app/templates/research_workspace.html").read_text(encoding="utf-8")
    assert 'href="/account"' in nav
    assert "filter_action|default('/admin')" in (ROOT / "app/templates/admin_filters.html").read_text(encoding="utf-8")
    accounts = (ROOT / "app/templates/admin_users_page.html").read_text(encoding="utf-8")
    assert 'method="get" action="/admin/users"' in accounts
    assert "extends 'admin_base.html'" in admin
    assert "/static/js/vietlex.js" not in admin
    assert 'type="hidden" name="evidence_a"' in workspace
    assert 'include "product_nav.html"' in workspace


def test_admin_detail_separates_external_http_calls_from_llm_tokens() -> None:
    html = (ROOT / "app/templates/admin_details.html").read_text(encoding="utf-8")
    usage = (ROOT / "app/templates/admin_usage.html").read_text(encoding="utf-8")

    assert "Các lần gọi dịch vụ ngoài không dùng token LLM" in html
    assert "external_calls" in html
    assert "HTTP request" in html
    assert "Official web / metadata kết quả" in html
    assert "Rà soát tài liệu người dùng" in html
    assert "Provider / model tạo câu trả lời" not in usage
