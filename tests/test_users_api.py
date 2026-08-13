"""Starlette 1.3.1's TestClient transport no longer applies the cookie jar,
so auth tests pass the session cookie as a raw header via helpers."""

from tests import helpers


def test_register_endpoint_removed(client):
    resp = client.get("/api/auth/register")
    assert resp.status_code == 404


def test_login_as_seeded_admin(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"username": "admin", "role": "admin"}
    headers = helpers.admin_headers(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me == {"username": "admin", "role": "admin"}


def test_login_wrong_password_401(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong!!"},
    )
    assert resp.status_code == 401


def test_login_unknown_user_401(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "secret123"},
    )
    assert resp.status_code == 401


def test_me_without_login_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_flow(client):
    headers = helpers.admin_headers(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
