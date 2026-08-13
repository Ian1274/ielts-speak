"""Shared test helpers for auth'd API calls.

Starlette 1.3.1's TestClient transport ignores both the cookie jar and
per-request cookies, so auth must travel as a raw Cookie header.
"""

COOKIE_NAME = "ielts_session"


def auth_headers(client, username, password):
    """Log in and return a raw Cookie header dict for authenticated requests."""
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Cookie": f"{COOKIE_NAME}={resp.cookies[COOKIE_NAME]}"}


def admin_headers(client):
    """Seeded admin (IELTS_ADMIN_USER/PASSWORD from conftest)."""
    return auth_headers(client, "admin", "secret123")
