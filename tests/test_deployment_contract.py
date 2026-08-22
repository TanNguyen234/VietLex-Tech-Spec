import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_is_a_thin_proxy_with_environment_only_origin() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    proxy = (ROOT / "api/proxy.py").read_text(encoding="utf-8")

    assert config["rewrites"]
    assert "BACKEND_ORIGIN" in proxy
    assert "YOUR-BACKEND" not in json.dumps(config)
    assert "data/" not in json.dumps(config)


def test_container_uses_persistent_corpus_paths_without_copying_data() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "VOLUME [\"/data\"]" in dockerfile
    assert "CONTENT_STORE_PATH=/data/content_store.sqlite3" in dockerfile
    assert "LEGAL_FTS_PATH=/data/legal_fts.sqlite3" in dockerfile
    assert "COPY data/" not in dockerfile
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
