from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "vietlex-lean-superpowers" / "SKILL.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"
EVALS_PATH = SKILL_PATH.parent / "evals" / "evals.json"


def _skill_text() -> str:
    assert SKILL_PATH.is_file(), f"missing project-local skill: {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_lean_skill_is_small_and_triggered_by_token_efficient_vietlex_work() -> None:
    text = _skill_text()
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)$", text, re.DOTALL)
    assert match is not None
    frontmatter = match.group("frontmatter")
    body = match.group("body")

    assert "name: vietlex-lean-superpowers" in frontmatter
    assert re.search(r"^description: Use when ", frontmatter, re.MULTILINE)
    assert "reduce token" in frontmatter.lower()
    assert len(re.findall(r"\b\w+[\w'-]*\b", body)) <= 380


def test_lean_skill_preserves_quality_and_authority_boundaries() -> None:
    text = _skill_text().lower()

    required_phrases = (
        "get_minimal_context_tool",
        "validate",
        "source",
        "test-driven-development",
        "focused",
        "full suite",
        "detect_changes_tool",
        "commit",
        "local merge",
        "push",
        "ingestion",
        "evidence promotion",
    )
    for phrase in required_phrases:
        assert phrase in text

    assert text.index("get_minimal_context_tool") < text.index("detect_changes_tool")
    assert "never weaken" in text
    assert "does not authorize" in text


def test_lean_skill_requires_fresh_full_verification_and_explicit_git_authority() -> None:
    text = _skill_text().lower()

    assert (
        "if source changes after the full suite, rerun the full suite before integration"
        in text
    )
    assert "explicit current-task authority" in text
    assert re.search(
        r"commit and local merge only when explicit current-task authority grants them",
        text,
    )


def test_lean_skill_keeps_crg_updates_read_only_safe() -> None:
    text = _skill_text().lower()

    assert "read-only task" in text
    assert "do not update the graph" in text
    assert "graph is stale" in text
    assert "mutation authority" in text


def test_project_local_lean_skill_is_not_ignored() -> None:
    gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")

    assert ".worktrees/" in gitignore
    assert ".agents/*" in gitignore
    assert "!.agents/skills/" in gitignore
    assert ".agents/skills/*" in gitignore
    assert "!.agents/skills/vietlex-lean-superpowers/" in gitignore
    assert "!.agents/skills/vietlex-lean-superpowers/**" in gitignore


def test_lean_skill_probes_reality_before_freezing_the_plan() -> None:
    text = _skill_text().lower()

    assert "reality probe" in text
    assert "plan freeze" in text
    assert "pinned artifact" in text
    assert "boundary/invariant" in text
    assert text.index("reality probe") < text.index("plan freeze")
    assert text.index("plan freeze") < text.index("test-driven-development")


def test_lean_skill_delays_expensive_verification_until_review_is_clean() -> None:
    text = _skill_text().lower()

    assert "final review" in text
    assert "review-clean" in text
    assert "broader/full once" in text
    assert "unresolved important finding" in text
    assert text.index("final review") < text.index("broader/full once")


def test_lean_skill_limits_agent_polling_and_review_artifacts() -> None:
    text = _skill_text().lower()

    assert "do not inspect shared diff/status while an agent runs" in text
    assert "one changed-state update" in text
    assert "reviewer inspects the git range directly" in text
    assert "review package only when repo access is unavailable" in text


def test_lean_skill_uses_risk_based_agents_and_commit_budget() -> None:
    text = _skill_text().lower()

    assert "bounded work: terra" in text
    assert "high-risk/final review: sol" in text
    assert "one review-clean commit per task" in text
    assert "do not commit each review round" in text


def test_lean_skill_integrates_official_crg_entry_and_review_tools() -> None:
    text = _skill_text().lower()

    assert "codex-research-automation:crg-code-review" in text
    assert "mcp__crg__get_minimal_context_tool" in text
    assert "mcp__crg__detect_changes_tool" in text
    assert "mcp__crg__query_graph_tool" in text
    assert text.index("mcp__crg__get_minimal_context_tool") < text.index(
        "mcp__crg__detect_changes_tool"
    )
    assert "for changed-code review call `mcp__crg__detect_changes_tool`" in text
    assert "read-only fallback: use `rg`/source; do not update the graph" in text


def test_lean_skill_keeps_automatic_worktree_creation_off() -> None:
    text = _skill_text().lower()

    assert "superpowers:using-git-worktrees` default: **off**" in text
    assert "do not create a worktree unless the user/task explicitly requests one" in text
    assert "reuse an existing worktree" in text


def test_lean_skill_distinguishes_feature_review_from_target_integration() -> None:
    text = _skill_text().lower()

    assert "combined feature diff" in text
    assert "target-branch integration" in text
    assert text.index("combined feature diff") < text.index("target-branch integration")


def test_reality_probe_eval_freezes_contract_before_fixture_updates() -> None:
    payload = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    expected = next(item for item in payload["evals"] if item["id"] == 3)[
        "expected_output"
    ].lower()

    assert "freeze the contract" in expected
    assert "then update fixtures through red tdd" in expected
    assert expected.index("freeze the contract") < expected.index("update fixtures")


def test_lean_skill_closes_crg_untracked_and_stale_coverage_gaps() -> None:
    text = _skill_text().lower()

    assert "git status --short" in text
    assert "untracked" in text
    assert "crg coverage" in text
    assert "direct source review" in text


def test_lean_skill_reviews_error_paths_before_stable_verification() -> None:
    text = _skill_text().lower()

    assert "error-path gate" in text
    assert "unexpected failures" in text
    assert text.index("error-path gate") < text.index("full suite")


def test_lean_skill_makes_durable_artifacts_last_and_invalidatable() -> None:
    text = _skill_text().lower()

    assert "artifacts last" in text
    assert "source/config" in text
    assert "regenerate" in text
    assert text.index("full suite") < text.index("artifacts last")


def test_lean_skill_bounds_tool_probes_and_self_reflection() -> None:
    text = _skill_text().lower()

    assert "probe a preferred tool once" in text
    assert "milestone-only reflection" in text
    assert "novel failure" in text
