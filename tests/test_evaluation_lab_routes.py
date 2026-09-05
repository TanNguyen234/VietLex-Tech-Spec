from fastapi import FastAPI
from fastapi.testclient import TestClient


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
