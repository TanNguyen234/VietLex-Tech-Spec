from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import optional_user
from app.api.routes import router


def test_retrieval_inspector_is_owner_scoped_and_handles_missing_trace(
    monkeypatch,
) -> None:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.client_id = "owner-a"
        return await call_next(request)

    app.dependency_overrides[optional_user] = lambda: None
    app.include_router(router)
    owned = AsyncMock(
        side_effect=[
            {
                "trace_id": "trace-1",
                "retrieval_trace": {
                    "status": "available",
                    "backend": "vertex-qdrant-v3",
                },
            },
            None,
        ]
    )
    monkeypatch.setattr("app.api.routes.get_owned_interaction", owned)
    client = TestClient(app)

    response = client.get("/api/interactions/trace-1/retrieval")

    assert response.status_code == 200
    assert response.json()["backend"] == "vertex-qdrant-v3"
    assert client.get("/api/interactions/missing/retrieval").status_code == 404
