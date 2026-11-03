import time
from types import SimpleNamespace

import httpx

from scripts.audit_online_capacity import (
    _audit_supabase,
    _qdrant_get,
    _scroll_ids,
    balance_candidate_queues,
    candidate_exclusion_reasons,
    parse_content_range_total,
    qdrant_memory_totals,
)


def _timeout_parts(timeout):
    if isinstance(timeout, httpx.Timeout):
        return {
            name: getattr(timeout, name)
            for name in ("connect", "read", "write", "pool")
        }
    return {"all": float(timeout)}


class _RecordingClient:
    timeout = httpx.Timeout(20.0)

    def __init__(self):
        self.timeouts = []

    def get(self, url, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        if url.endswith("/rest/v1/legal_documents"):
            return httpx.Response(200, json=[{"document_id": 42}])
        return httpx.Response(200, json={"result": {}})

    def post(self, url, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        return httpx.Response(200, json={"result": {"points": [], "next_page_offset": None}})

    def head(self, url, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        return httpx.Response(200, headers={"content-range": "0-0/1"})


def test_online_requests_never_expand_httpx_client_timeout_to_audit_deadline():
    deadline = time.monotonic() + 300
    client = _RecordingClient()

    payload, error = _qdrant_get(client, "https://qdrant.invalid", "test", "/collections", deadline)
    assert error is None
    assert payload == {"result": {}}
    _scroll_ids(client, "https://qdrant.invalid", "test", "collection", deadline)
    _audit_supabase(
        client,
        SimpleNamespace(SUPABASE_URL="https://supabase.invalid", SUPABASE_PUBLISHABLE_KEY="test"),
        deadline,
    )

    assert len(client.timeouts) == 4
    for timeout in client.timeouts:
        assert all(value is None or value <= 20 for value in _timeout_parts(timeout).values())


def test_qdrant_get_supports_injected_clients_without_timeout_metadata():
    class InjectedClient:
        timeout_sent = None

        def get(self, url, **kwargs):
            self.timeout_sent = kwargs["timeout"]
            return httpx.Response(200, json={"result": {}})

    client = InjectedClient()
    payload, error = _qdrant_get(
        client,
        "https://qdrant.invalid",
        "test",
        "/collections",
        time.monotonic() + 30,
    )

    assert error is None
    assert payload == {"result": {}}
    assert isinstance(client.timeout_sent, float)
    assert 0 < client.timeout_sent <= 30


def test_parse_exact_count_from_postgrest_content_range():
    assert parse_content_range_total("0-0/14962") == 14962
    assert parse_content_range_total("*/0") == 0
    assert parse_content_range_total("0-0/*") is None
    assert parse_content_range_total("not-a-range") is None


def test_balanced_candidates_are_stable_and_use_round_robin_order():
    queues = {
        "Luật": [{"document_id": 1}, {"document_id": 2}],
        "Nghị định": [{"document_id": 3}, {"document_id": 4}],
        "Thông tư": [{"document_id": 5}, {"document_id": 6}],
    }

    selected = balance_candidate_queues(
        queues,
        legal_types=["Luật", "Nghị định", "Thông tư"],
        limit=5,
    )

    assert [row["document_id"] for row in selected] == [1, 3, 5, 2, 4]
    assert selected == balance_candidate_queues(
        queues,
        legal_types=["Luật", "Nghị định", "Thông tư"],
        limit=5,
    )


def test_candidate_quality_filter_matches_builder_without_dropping_duplicate_hash():
    assert candidate_exclusion_reasons({"missing_title", "duplicate_content_hash"}) == (
        "missing_title",
    )
    assert candidate_exclusion_reasons({"invalid_issuance_date", "abnormal_length"}) == ()


def test_qdrant_memory_uses_total_without_double_counting_components():
    memory = {
        "total": {"disk": 100, "ram": 20, "cached": 30},
        "vectors": {"disk": 70, "ram": 10, "cached": 20},
        "payload": {"disk": 30, "ram": 10, "cached": 10},
    }

    assert qdrant_memory_totals(memory) == {
        "disk_bytes": 100,
        "ram_bytes": 20,
        "cached_bytes": 30,
        "expected_cache_bytes": None,
    }


def test_qdrant_memory_reads_actual_bytes_schema_and_prefers_server_total():
    memory = {
        "total": {
            "disk_bytes": 100,
            "ram_bytes": 20,
            "cached_bytes": 30,
            "expected_cache_bytes": 40,
        },
        "vectors": {
            "disk_bytes": 70,
            "ram_bytes": 10,
            "cached_bytes": 20,
            "expected_cache_bytes": 25,
        },
        "payload": {
            "disk_bytes": 30,
            "ram_bytes": 10,
            "cached_bytes": 10,
            "expected_cache_bytes": 15,
        },
    }

    assert qdrant_memory_totals(memory) == {
        "disk_bytes": 100,
        "ram_bytes": 20,
        "cached_bytes": 30,
        "expected_cache_bytes": 40,
    }


def test_qdrant_memory_sums_component_leaves_when_total_is_missing():
    memory = {
        "vectors": {"disk": 70, "ram": 10, "cached": 20},
        "payload": {"disk": 30, "ram": 10, "cached": 10},
    }

    assert qdrant_memory_totals(memory) == {
        "disk_bytes": 100,
        "ram_bytes": 20,
        "cached_bytes": 30,
        "expected_cache_bytes": None,
    }
