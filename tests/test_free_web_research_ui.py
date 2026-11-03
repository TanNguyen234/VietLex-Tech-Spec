from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_saved_free_web_analysis_serializes_research_mode_for_reload_renderer():
    template = (ROOT / "app/templates/research_workspace.html").read_text(encoding="utf-8")

    assert "'research_mode':analysis.research_mode|default(none)" in template


def test_saved_free_web_render_shows_terminal_errors_read_time_and_omits_ocr_warning():
    script = (ROOT / "app/static/js/research-workspace.js").read_text(encoding="utf-8")

    assert "payload.research_mode === 'free_web_research'" in script
    assert "researchResult.terminal" in script
    assert "researchResult.source_errors" in script
    assert "source.snapshot_timestamp || source.retrieved_at" in script
    assert "OCR có thể đọc sai" in script  # Generic official-source reader remains intact.
    assert "Không dùng lượt AI/OCR" in script
    workflow_css = (ROOT / "app/static/css/research-workflow.css").read_text(encoding="utf-8")
    assert "button[data-cancel-free-research][hidden]{display:none!important}" in workflow_css


def test_free_research_cancel_waits_for_durable_start_and_server_ack_before_abort():
    script = (ROOT / "app/static/js/research-workspace.js").read_text(encoding="utf-8")

    assert "if (parsed.type === 'started' && freeCancelButton) freeCancelButton.disabled = false;" in script
    cancel_request = script.index("/research/runs/' + encodeURIComponent(runId) + '/cancel")
    cancel_ack = script.index("freeResearchCancelRecorded = true;", cancel_request)
    abort = script.index("controller.abort();", cancel_ack)
    assert cancel_request < cancel_ack < abort
    assert "Chưa xác nhận được hủy" in script


def test_stale_cancel_response_cannot_mutate_a_new_free_research_run():
    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("Node.js is required to exercise the real cancellation handler")
    race_test = ROOT / "tests/free_research_cancel_race.test.cjs"
    result = subprocess.run(
        [node, "--test", str(race_test)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
