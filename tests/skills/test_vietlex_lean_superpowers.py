from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / ".agents" / "skills" / "vietlex-lean-superpowers" / "SKILL.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


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
    assert len(re.findall(r"\b\w+[\w'-]*\b", body)) <= 320


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

    assert ".agents/*" in gitignore
    assert "!.agents/skills/" in gitignore
    assert ".agents/skills/*" in gitignore
    assert "!.agents/skills/vietlex-lean-superpowers/" in gitignore
    assert "!.agents/skills/vietlex-lean-superpowers/**" in gitignore
