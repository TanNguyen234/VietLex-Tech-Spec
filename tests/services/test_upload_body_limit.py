from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest


def test_workspace_upload_body_limit_rejects_content_length_and_streamed_body() -> None:
    from app.services.http_security import WorkspaceUploadBodyLimitMiddleware

    app = FastAPI()
    app.add_middleware(WorkspaceUploadBodyLimitMiddleware, max_bytes=10)

    @app.post("/workspaces/w-1/documents")
    async def upload(request: Request):
        return {"length": len(await request.body())}

    client = TestClient(app)
    assert client.post(
        "/workspaces/w-1/documents", content=b"x" * 11
    ).status_code == 413
    assert client.post("/unrelated", content=b"x" * 11).status_code == 404
    assert client.post(
        "/workspaces/w-1/documents", content=b"x" * 10
    ).status_code == 200


@pytest.mark.asyncio
async def test_chunked_upload_is_bounded_before_downstream_parser():
    from app.services.http_security import WorkspaceUploadBodyLimitMiddleware
    from unittest.mock import AsyncMock
    downstream = AsyncMock()
    middleware = WorkspaceUploadBodyLimitMiddleware(downstream, max_bytes=10)
    receive = AsyncMock(side_effect=[
        {'type': 'http.request', 'body': b'a' * 6, 'more_body': True},
        {'type': 'http.request', 'body': b'b' * 6, 'more_body': False},
    ])
    send = AsyncMock()
    await middleware({'type': 'http', 'method': 'POST', 'path': '/workspaces/w/documents', 'headers': []}, receive, send)
    downstream.assert_not_awaited()
    assert send.await_args_list[0].args[0]['status'] == 413


def test_upload_ip_limit_cannot_be_reset_by_cookie_changes():
    from app.services.http_security import WorkspaceUploadBodyLimitMiddleware
    app = FastAPI()
    app.add_middleware(WorkspaceUploadBodyLimitMiddleware, max_bytes=10)
    client = TestClient(app)
    for i in range(6):
        response = client.post('/workspaces/w/documents', content=b'x', headers={'cookie': f'client={i}'})
        assert response.status_code == 404
    assert client.post('/workspaces/w/documents', content=b'x').status_code == 429
