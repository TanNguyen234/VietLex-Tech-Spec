import importlib
from pathlib import Path


def _checkpoint_module():
    return importlib.import_module("app.ingestion.checkpoint")


def test_completed_batches_are_skipped_on_resume(tmp_path: Path) -> None:
    checkpoint = _checkpoint_module()
    store = checkpoint.CheckpointStore(
        tmp_path / "state.sqlite3",
        revision="rev",
    )
    store.mark_completed(
        batch_id=0,
        first_id=1,
        last_id=256,
        point_count=256,
        seconds=2.0,
    )

    assert store.completed_batch_ids() == {0}
    assert store.next_incomplete([0, 1, 2]) == 1


def test_failure_messages_are_sanitized(tmp_path: Path) -> None:
    checkpoint = _checkpoint_module()
    store = checkpoint.CheckpointStore(
        tmp_path / "state.sqlite3",
        revision="rev",
        secrets=("secret-token",),
    )
    store.record_failure(
        document_id=42,
        stage="embedding",
        category="authorization",
        message="Bearer secret-token rejected",
        attempts=1,
    )

    failure = store.failures()[0]
    assert "secret-token" not in failure.message
    assert "[REDACTED]" in failure.message


def test_successful_resume_clears_prior_batch_failures(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint_module()
    store = checkpoint.CheckpointStore(
        tmp_path / "state.sqlite3",
        revision="rev",
    )
    store.record_failure(
        document_id=42,
        stage="embedding_or_upload",
        category="timeout",
        message="temporary failure",
        attempts=1,
    )

    store.clear_failures(
        document_ids=[42],
        stage="embedding_or_upload",
    )

    assert store.failures() == []
