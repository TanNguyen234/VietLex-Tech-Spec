"""Khách mở trang bằng điều hướng trình duyệt không được nhận JSON 401 thô; fetch() vẫn giữ hành vi cũ."""

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_guest_opening_settings_in_browser_is_sent_to_login(client):
    response = client.get(
        "/settings",
        headers={"Sec-Fetch-Dest": "document", "Accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_guest_fetch_to_settings_keeps_json_401(client):
    response = client.get(
        "/settings",
        headers={"Sec-Fetch-Dest": "empty", "Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_admin_page_in_browser_is_sent_to_login_not_raw_401(client):
    response = client.get(
        "/admin",
        headers={"Sec-Fetch-Dest": "document", "Accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_sessions_fragment_opened_directly_redirects_home(client):
    response = client.get(
        "/sessions",
        headers={"Sec-Fetch-Dest": "document", "Accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
