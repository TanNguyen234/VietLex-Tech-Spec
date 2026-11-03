from __future__ import annotations

from typing import Any
import re


class SourceReadError(RuntimeError):
    def __init__(self, kind, *, transport_kind: str | None = None, transport_cause: str | None = None):
        super().__init__(kind)
        self.kind = kind
        self.transport_kind = transport_kind
        self.transport_cause = transport_cause


GUARDRAIL_UNAVAILABLE_MESSAGE = (
    "Hệ thống kiểm tra an toàn đang tạm thời không khả dụng. "
    "Vui lòng thử lại sau."
)


def guardrail_error_reason(reason: object) -> str:
    if isinstance(reason, str) and (
        reason in {"timeout", "dependency_unavailable", "invalid_generation_result",
                   "generation_incomplete", "invalid_decision", "configuration_invalid", "unavailable"}
        or re.fullmatch(r"[A-Z][A-Za-z0-9_]{0,60}(?:Error|Exception)", reason)
    ):
        return reason
    return "unavailable"


class GuardrailUnavailableError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage} guardrail unavailable: {reason}")


class RetrievalPipelineError(RuntimeError):
    def __init__(
        self,
        status: str,
        message: str,
        diagnostics: dict[str, Any],
        latency: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.diagnostics = diagnostics
        self.latency = latency or {}
