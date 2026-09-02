# Gemini workspace entry point

Root [`AGENTS.md`](AGENTS.md) is mandatory and overrides this compatibility
file. Read the current documentation map in
[`docs/DOCUMENTATION_INDEX.md`](docs/DOCUMENTATION_INDEX.md) before treating a
plan, report, or architecture file as current.

## Repository exploration

Code Review Graph (CRG) is preferred for relationship and impact analysis when
its MCP tools are available and its graph covers the current source state:

1. Call `get_minimal_context_tool` first.
2. Use directed graph queries for callers, imports, tests, and change impact.
3. Validate important graph conclusions against source.
4. Compare graph coverage with `git status --short` because untracked or newer
   files may be absent.

If CRG is unavailable, stale, or missing the relevant file, use `rg` and
bounded source reads. Do not claim that a graph auto-updated unless the tool
actually reports the updated state. Do not install or activate non-Codex hooks
as Codex lifecycle hooks.
