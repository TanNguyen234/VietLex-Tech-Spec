import importlib
import os
import threading
import time

import pytest


def _pipeline_module():
    return importlib.import_module("app.ingestion.hf_pipeline")


def _passing_preflight():
    pipeline = _pipeline_module()
    return pipeline.PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        pinecone_configured=True,
        qdrant_inference_configured=True,
        reranker_configured=True,
        joined_count=518_255,
    )


def test_destructive_preflight_requires_every_service_gate() -> None:
    pipeline = _pipeline_module()
    result = pipeline.PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        pinecone_configured=True,
        qdrant_inference_configured=True,
        reranker_configured=False,
        joined_count=518_255,
    )

    with pytest.raises(RuntimeError, match="reranker"):
        pipeline.assert_destructive_preflight(result)


def test_full_success_requires_exact_remote_count() -> None:
    pipeline = _pipeline_module()
    result = pipeline.PreflightResult(
        snapshot_verified=True,
        content_store_verified=True,
        pinecone_configured=True,
        qdrant_inference_configured=True,
        reranker_configured=True,
        joined_count=518_254,
    )

    with pytest.raises(RuntimeError, match="joined_count_518255"):
        pipeline.assert_destructive_preflight(result)


def test_parser_requires_destructive_flags_for_full_phase() -> None:
    pipeline = _pipeline_module()
    parser = pipeline.build_parser()

    parsed = parser.parse_args(
        ["full", "--delete-existing", "--yes"]
    )

    assert parsed.phase == "full"
    assert parsed.delete_existing is True
    assert parsed.yes is True


def test_passing_preflight_has_no_failed_gate() -> None:
    pipeline = _pipeline_module()

    pipeline.assert_destructive_preflight(_passing_preflight())


def test_tuning_selects_fastest_zero_failure_candidate() -> None:
    pipeline = _pipeline_module()
    candidates = [
        pipeline.BenchmarkResult(
            name="safe-slow",
            documents=1_000,
            seconds=20.0,
            retries=0,
            throttles=0,
            permanent_failures=0,
            configuration={"embed_concurrency": 4},
        ),
        pipeline.BenchmarkResult(
            name="fast-broken",
            documents=1_000,
            seconds=5.0,
            retries=0,
            throttles=0,
            permanent_failures=1,
            configuration={"embed_concurrency": 16},
        ),
        pipeline.BenchmarkResult(
            name="safe-fast",
            documents=1_000,
            seconds=10.0,
            retries=1,
            throttles=0,
            permanent_failures=0,
            configuration={"embed_concurrency": 8},
        ),
    ]

    selected = pipeline.select_tuning_candidate(candidates)

    assert selected.name == "safe-fast"
    assert selected.documents_per_second == 100.0


def test_batch_numbers_remain_stable_when_completed_batches_are_skipped() -> None:
    pipeline = _pipeline_module()

    pending = list(
        pipeline.iter_numbered_batches(
            [10, 20, 30, 40, 50],
            batch_size=2,
            completed_batch_ids={1},
        )
    )

    assert pending == [(0, [10, 20]), (2, [50])]


def test_benchmark_sample_does_not_consume_full_corpus() -> None:
    pipeline = _pipeline_module()
    consumed: list[int] = []

    def ids():
        for document_id in range(10):
            consumed.append(document_id)
            yield document_id

    selected = pipeline.take_document_ids(ids(), limit=3)

    assert selected == [0, 1, 2]
    assert consumed == [0, 1, 2]


def test_benchmark_sample_is_deterministically_spread_across_corpus() -> None:
    pipeline = _pipeline_module()

    selected = pipeline.sample_document_ids(
        range(100),
        population_size=100,
        limit=10,
    )

    assert selected == list(range(0, 100, 10))


def test_live_benchmark_uses_bounded_power_of_two_samples() -> None:
    pipeline = _pipeline_module()

    assert pipeline.TUNING_SAMPLE_SIZE == 256
    assert pipeline.BENCHMARK_SAMPLE_SIZE == 1_024


def test_speedup_target_is_reported_without_rejecting_a_real_gain() -> None:
    pipeline = _pipeline_module()

    assessment = pipeline.assess_benchmark_speedup(1.64)

    assert assessment == {
        "target_speedup": 3.0,
        "target_met": False,
    }


def test_benchmark_rejects_an_optimized_configuration_that_is_slower() -> None:
    pipeline = _pipeline_module()

    with pytest.raises(RuntimeError, match="slower than baseline"):
        pipeline.assess_benchmark_speedup(0.99)


@pytest.mark.asyncio
async def test_prepared_batches_upload_concurrently_and_report_each_result() -> None:
    pipeline = _pipeline_module()
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def uploader(client, settings, points):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    batches = [
        pipeline.PreparedBatch(
            batch_id=batch_id,
            document_ids=[batch_id],
            points=[],
            started_at=time.perf_counter(),
        )
        for batch_id in range(4)
    ]

    outcomes = await pipeline.upload_prepared_batches(
        client=object(),
        settings=object(),
        batches=batches,
        uploader=uploader,
    )

    assert maximum_active >= 2
    assert [outcome.batch.batch_id for outcome in outcomes] == list(range(4))
    assert all(outcome.error is None for outcome in outcomes)


def test_sparse_work_is_partitioned_across_available_processes() -> None:
    pipeline = _pipeline_module()

    partitions = pipeline.partition_sparse_texts(
        [str(index) for index in range(7)],
        workers=3,
    )

    assert partitions == [
        ["0", "1", "2"],
        ["3", "4", "5"],
        ["6"],
    ]


def test_resume_rejects_changed_upload_batch_size() -> None:
    pipeline = _pipeline_module()

    with pytest.raises(RuntimeError, match="batch size"):
        pipeline.assert_resume_batch_size(
            completed_batch_ids={0, 1},
            checkpoint_metrics={"upload_batch_size": [128.0]},
            upload_batch_size=256,
        )


def test_pipeline_temp_files_are_redirected_to_project_storage(
    tmp_path,
) -> None:
    pipeline = _pipeline_module()
    destination = tmp_path / "pipeline-temp"

    resolved = pipeline.configure_process_temp(destination)

    assert resolved == destination.resolve()
    assert os.environ["TEMP"] == str(resolved)
    assert os.environ["TMP"] == str(resolved)


@pytest.mark.asyncio
async def test_prepare_batch_uses_separate_dense_and_sparse_texts(
    monkeypatch,
) -> None:
    pipeline = _pipeline_module()
    captured: dict[str, list[str]] = {}
    document = type(
        "Document",
        (),
        {"metadata": object(), "content": "toàn bộ nội dung"},
    )()
    batch = pipeline.BatchInput(
        batch_id=7,
        document_ids=[1],
        documents=[document],
        started_at=time.perf_counter(),
    )

    monkeypatch.setattr(
        pipeline,
        "build_dense_text",
        lambda *_args, **_kwargs: "DENSE REPRESENTATION",
    )
    monkeypatch.setattr(
        pipeline,
        "build_sparse_text",
        lambda *_args, **_kwargs: "SPARSE REPRESENTATION",
    )

    def fake_extract(_client, _settings, texts, *, slot):
        captured["dense"] = texts
        return [[0.0, 0.0]]

    class SparseEncoder:
        def encode_document(self, text: str):
            captured.setdefault("sparse", []).append(text)
            return {"indices": [1], "values": [1.0]}

    monkeypatch.setattr(pipeline, "extract_dense_vectors", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "build_record",
        lambda **kwargs: kwargs,
    )

    prepared = await pipeline._prepare_batch(
        batch,
        slot=0,
        settings=object(),
        qdrant=object(),
        qdrant_semaphore=__import__("asyncio").Semaphore(1),
        sparse_encoder=SparseEncoder(),
    )

    assert captured == {
        "dense": ["DENSE REPRESENTATION"],
        "sparse": ["SPARSE REPRESENTATION"],
    }
    assert len(prepared.points) == 1
