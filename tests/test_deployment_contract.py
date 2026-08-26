import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_is_a_thin_proxy_with_environment_only_origin() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    proxy = (ROOT / "api/proxy.py").read_text(encoding="utf-8")

    assert config["rewrites"]
    assert "BACKEND_ORIGIN" in proxy
    assert "YOUR-BACKEND" not in json.dumps(config)
    assert "data/" not in json.dumps(config)


def test_vercel_bundle_contains_only_stdlib_proxy_files() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    ignore = (ROOT / ".vercelignore").read_text(encoding="utf-8")
    proxy = (ROOT / "api/proxy.py").read_text(encoding="utf-8")

    assert "/*" in ignore
    assert "!api" in ignore and "!vercel.json" in ignore
    assert "!requirements.txt" not in ignore
    assert config["functions"]["api/proxy.py"]["maxDuration"] == 60
    assert "timeout=55" in proxy
    assert "X-Forwarded-Proto" in proxy


def test_vercel_marks_buffered_progress_transport() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    index = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/vietlex.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "gateway=vercel" in config["rewrites"][0]["destination"]
    assert "progress_transport" in main
    assert "data-progress-transport" in index
    assert "progressTransport" in script
    assert "setTimeout(poll,1000)" in script


def test_runtime_selects_progress_transport_without_leaking_local_env() -> None:
    script = """
import json
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
vercel = client.get('/?gateway=vercel')
direct = client.get('/')
print(json.dumps({
    'vercel_status': vercel.status_code,
    'vercel_polling': 'data-progress-transport=\"polling\"' in vercel.text,
    'direct_status': direct.status_code,
    'direct_sse': 'data-progress-transport=\"sse\"' in direct.text,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "vercel_status": 200,
        "vercel_polling": True,
        "direct_status": 200,
        "direct_sse": True,
    }


def test_web_import_does_not_eagerly_load_ai_runtime() -> None:
    script = """
import json
import sys
from app.main import app
print(json.dumps({
    'guardrails': 'app.services.guardrails' in sys.modules,
    'rag_pipeline': 'app.services.rag_pipeline' in sys.modules,
    'transformers': 'transformers' in sys.modules,
    'torch': 'torch' in sys.modules,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "guardrails": False,
        "rag_pipeline": False,
        "transformers": False,
        "torch": False,
    }


def test_container_uses_persistent_corpus_paths_without_copying_data() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "VOLUME [\"/data\"]" in dockerfile
    assert "CONTENT_STORE_PATH=/data/content_store.sqlite3" in dockerfile
    assert "LEGAL_FTS_PATH=/data/legal_fts.sqlite3" in dockerfile
    assert "COPY data/" not in dockerfile
    assert "COPY guardrails_config/ ./guardrails_config/" in dockerfile
    assert "data/" in dockerignore


def test_demo_documentation_states_the_split_and_secret_boundary() -> None:
    deployment = (ROOT / "deploy/vercel-proxy/README.md").read_text(
        encoding="utf-8"
    )
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "BACKEND_ORIGIN" in deployment
    assert "persistent" in deployment.lower()
    assert "không" in deployment.lower() and "corpus" in deployment.lower()
    assert "WEB_SESSION_SECRET=" in example
    assert "ADMIN_PASSWORD=" in example
    assert "PUBLIC_RAGAS_ENABLED=false" in example


def test_production_operations_document_backup_and_restore_boundaries() -> None:
    operations = (ROOT / "docs/PRODUCTION_OPERATIONS.md").read_text(
        encoding="utf-8"
    )

    assert "MongoDB" in operations and "content_store.sqlite3" in operations
    assert "legal_fts.sqlite3" in operations and "rebuildable" in operations
    assert "Pinecone" in operations and "derived" in operations
    assert "restore" in operations.casefold()
    assert "GET /readyz" in operations
