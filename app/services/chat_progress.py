from __future__ import annotations

from collections import OrderedDict
import time
from typing import Any


class ChatProgressRegistry:
    """Bounded, process-local progress telemetry for the public demo UI."""

    def __init__(self, *, max_entries: int = 500, ttl_seconds: int = 600) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def start(self, request_id: str, client_id: str, *, nemo_enabled: bool) -> None:
        self._prune()
        self._entries[request_id] = {
            "client_id": client_id,
            "started_at": time.monotonic(),
            "updated_at": time.monotonic(),
            "stage": "accepted",
            "label": "Đã tiếp nhận câu hỏi",
            "complete": False,
            "status": "running",
            "nemo_enabled": nemo_enabled,
        }
        self._entries.move_to_end(request_id)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def advance(
        self, request_id: str, client_id: str, stage: str, label: str
    ) -> None:
        entry = self._owned_entry(request_id, client_id)
        if entry is None:
            return
        entry.update(stage=stage, label=label, updated_at=time.monotonic())

    def complete(self, request_id: str, client_id: str, *, status: str) -> None:
        entry = self._owned_entry(request_id, client_id)
        if entry is None:
            return
        entry.update(
            stage="complete",
            label="Đã hoàn tất",
            complete=True,
            status=status,
            updated_at=time.monotonic(),
        )

    def get(self, request_id: str, client_id: str) -> dict[str, Any] | None:
        self._prune()
        entry = self._owned_entry(request_id, client_id)
        if entry is None:
            return None
        return {
            key: value
            for key, value in entry.items()
            if key not in {"client_id", "started_at", "updated_at"}
        } | {"elapsed_seconds": round(time.monotonic() - entry["started_at"], 2)}

    def _owned_entry(self, request_id: str, client_id: str):
        entry = self._entries.get(request_id)
        return entry if entry and entry["client_id"] == client_id else None

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            request_id
            for request_id, entry in self._entries.items()
            if now - entry["updated_at"] > self._ttl_seconds
        ]
        for request_id in expired:
            self._entries.pop(request_id, None)


chat_progress = ChatProgressRegistry()
