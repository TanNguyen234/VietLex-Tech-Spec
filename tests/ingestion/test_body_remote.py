import hashlib
import json
from types import SimpleNamespace
import httpx
import pytest


def doc(text="Mở đầu\nĐiều 1. Thử việc\nNội dung\nĐiều 2. Quyền\nQuy định"):
    return SimpleNamespace(
        content=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        metadata=SimpleNamespace(document_id=7),
    )


def test_bundle_preserves_global_offsets_and_refuses_overwrite(tmp_path):
    from app.ingestion.body_remote import prepare_body_bundle

    source = doc()
    folder = tmp_path / "batch"
    manifest = prepare_body_bundle(folder, [source], max_documents=1)
    rows = [
        json.loads(s)
        for s in (folder / "passages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert (
        manifest["expected_documents"] == 1
        and len(rows) == manifest["expected_passages"]
    )
    for row in rows:
        start = row["document_offset"]
        assert source.content[start : start + len(row["body"])] == row["body"]
    assert rows[-1]["document_offset"] > 0
    with pytest.raises(FileExistsError):
        prepare_body_bundle(folder, [source], max_documents=1)


def test_corrupt_source_never_creates_ready_manifest(tmp_path):
    from app.ingestion.body_remote import prepare_body_bundle

    source = doc()
    source.content_sha256 = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        prepare_body_bundle(tmp_path / "bad", [source], max_documents=1)
    assert not (tmp_path / "bad" / "manifest.json").exists()


def test_upload_rejects_modified_bundle_before_network(tmp_path):
    from app.ingestion.body_remote import prepare_body_bundle, upload_body_bundle

    folder = tmp_path / "batch"
    prepare_body_bundle(folder, [doc()], max_documents=1)
    with (folder / "passages.jsonl").open("a", encoding="utf-8") as f:
        f.write("{}\n")

    def reject(request):
        raise AssertionError("must validate before network")

    with pytest.raises(ValueError, match="bundle"):
        upload_body_bundle(
            folder,
            url="https://project.supabase.co",
            service_key="test",
            client=httpx.Client(transport=httpx.MockTransport(reject)),
        )


def test_upload_stages_then_explicitly_publishes_and_checks_active_batch(tmp_path):
    from app.ingestion.body_remote import prepare_body_bundle, upload_body_bundle

    folder = tmp_path / "batch"
    manifest = prepare_body_bundle(folder, [doc()], max_documents=1)
    calls = []

    def respond(r):
        calls.append(r)
        if r.url.path.endswith("legal_body_coverage"):
            return httpx.Response(200, json={"batch_id": manifest["batch_id"]})
        return httpx.Response(201, json=None)

    result = upload_body_bundle(
        folder,
        url="https://project.supabase.co",
        service_key="test",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        publish=True,
    )
    assert (
        result["published"]
        and result["attempted_passages"] == manifest["expected_passages"]
    )
    assert [r.url.path.rsplit("/", 1)[-1] for r in calls] == [
        "legal_body_runs",
        "legal_body_passages",
        "publish_legal_body",
        "legal_body_coverage",
    ]
