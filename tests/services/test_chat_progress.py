from types import SimpleNamespace


def test_progress_registry_is_owner_scoped_and_reports_elapsed_time(monkeypatch) -> None:
    from app.services.chat_progress import ChatProgressRegistry

    clock = SimpleNamespace(value=100.0)
    monkeypatch.setattr("app.services.chat_progress.time.monotonic", lambda: clock.value)
    registry = ChatProgressRegistry(max_entries=5, ttl_seconds=60)

    registry.start("request-1", "owner-a", nemo_enabled=True)
    clock.value = 101.25
    registry.advance("request-1", "owner-a", "semantic_cache", "Đang kiểm tra cache")

    snapshot = registry.get("request-1", "owner-a")

    assert snapshot["stage"] == "semantic_cache"
    assert snapshot["label"] == "Đang kiểm tra cache"
    assert snapshot["elapsed_seconds"] == 1.25
    assert snapshot["nemo_enabled"] is True
    assert registry.get("request-1", "owner-b") is None


def test_progress_registry_marks_completion_and_evicts_old_entries(monkeypatch) -> None:
    from app.services.chat_progress import ChatProgressRegistry

    clock = SimpleNamespace(value=10.0)
    monkeypatch.setattr("app.services.chat_progress.time.monotonic", lambda: clock.value)
    registry = ChatProgressRegistry(max_entries=2, ttl_seconds=5)
    registry.start("one", "owner", nemo_enabled=False)
    registry.start("two", "owner", nemo_enabled=False)
    registry.complete("two", "owner", status="ok")
    registry.start("three", "owner", nemo_enabled=False)

    assert registry.get("one", "owner") is None
    assert registry.get("two", "owner")["complete"] is True
    clock.value = 20.0
    assert registry.get("two", "owner") is None
