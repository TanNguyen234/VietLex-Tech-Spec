from __future__ import annotations

from typing import Any


GUARDRAIL_UNAVAILABLE_MESSAGE = (
    "Hệ thống kiểm tra an toàn đang tạm thời không khả dụng. "
    "Vui lòng thử lại sau."
)


class GuardrailUnavailableError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
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
