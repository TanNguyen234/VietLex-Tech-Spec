from fastapi import FastAPI
from fastapi.testclient import TestClient
import json
from app.api.dependencies import require_admin


def test_evaluation_lab_route_renders_artifact_provenance(monkeypatch) -> None:
    from app.api.evaluation_lab_routes import router

    monkeypatch.setattr(
        "app.api.evaluation_lab_routes.load_evaluation_lab",
        lambda _path, case_id=None: {
            "status": "available",
            "boundary": "bounded",
            "provenance": {"run_id": "run-1", "git_dirty": True},
            "deterministic_metrics": {},
            "ragas_metrics": {},
            "cases": [],
            "case": None,
        },
    )
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/evaluation-lab")

    assert response.status_code == 200
    assert "run-1" in response.text
    assert "Git dirty" in response.text


def test_admin_evaluations_requires_admin_and_confines_run_paths(monkeypatch, tmp_path):
    import app.api.evaluation_lab_routes as routes

    run = tmp_path / "run-1"
    run.mkdir()
    (run / "manifest.json").write_text('{"run_id":"run-1"}')
    (run / "answer_results.json").write_text(
        json.dumps([{"case_id": "a", "status": "ok", "metrics": {"token_f1": 0.25}}])
    )
    monkeypatch.setattr(routes, "RUNS_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    assert client.get("/admin/evaluations").status_code in {401, 403}
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    result = client.get("/admin/evaluations?run=run-1&case=a")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert "0.2500" in result.text and "run-1" in result.text
    assert (
        client.get("/admin/evaluations", params={"run": "../secret"}).status_code == 404
    )
    assert client.get("/admin/evaluations?run=missing").status_code == 404


def test_admin_evaluations_reports_unreadable_catalog(monkeypatch):
    import app.api.evaluation_lab_routes as routes

    def unavailable():
        raise OSError("private filesystem path")

    monkeypatch.setattr(routes, "_available_runs", unavailable)
    app = FastAPI()
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.include_router(routes.router)
    response = TestClient(app).get("/admin/evaluations")
    assert response.status_code == 503
    assert "run_catalog_unavailable" in response.text
    assert "private filesystem path" not in response.text
    assert response.headers["cache-control"] == "no-store"
