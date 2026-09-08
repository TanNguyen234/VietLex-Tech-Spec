"""Bounded structured-output diagnostics without model text or private inputs."""

from pydantic import ValidationError


_FIELDS = frozenset({
    "status", "issue", "analysis", "exceptions", "checklist", "sources", "unknown",
    "text", "evidence_ids", "claims", "claim_id", "verdict", "quotes",
    "evidence_id", "quote",
})
_CODES = frozenset({
    "report_claim_must_be_atomic", "report_claim_scope_too_large",
    "claim_scope_too_large", "claim_scope_empty", "claim_coverage_invalid",
    "invalid_evidence_quote", "invalid_evidence_reference", "report_sources_incomplete",
    "output_token_limit",
})

# Live Vertex evidence: the old 2,000 cap cut JSON after 1,746 thinking + 250
# response tokens. Keep a finite combined budget; never retry truncated output.
REPORT_MAX_OUTPUT_TOKENS = 4_096


def generation_diagnostics(generation) -> dict:
    return {
        key: getattr(generation, key, None)
        for key in (
            "finish_reason", "prompt_token_count", "output_token_count",
            "thought_token_count", "total_token_count", "fallback_used",
            "primary_error_kind",
        )
    }


def validation_diagnostics(error: ValueError) -> dict:
    if not isinstance(error, ValidationError):
        return {"error_code": str(error) if str(error) in _CODES else "validation_error"}
    errors = error.errors(include_input=False, include_context=False, include_url=False)
    return {
        "validation_error_count": len(errors),
        "validation_errors": [
            {
                "type": item["type"],
                "loc": [part if isinstance(part, int) or part in _FIELDS else "<field>"
                        for part in item["loc"]],
                **({"code": item["msg"].removeprefix("Value error, ")}
                   if item["msg"].removeprefix("Value error, ") in _CODES else {}),
            }
            for item in errors[:20]
        ],
    }
