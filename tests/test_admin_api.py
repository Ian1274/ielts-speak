from tests import helpers


def _create_user(client, headers, name, password="secret123", role="user"):
    return client.post(
        "/api/admin/users",
        json={"username": name, "password": password, "role": role},
        headers=headers,
    )


def test_non_admin_forbidden(client):
    admin_h = helpers.admin_headers(client)
    _create_user(client, admin_h, "bob")
    bob_h = helpers.auth_headers(client, "bob", "secret123")
    assert client.get("/api/admin/users", headers=bob_h).status_code == 403
    assert _create_user(client, bob_h, "carol").status_code == 403


def test_admin_list_users_with_stats(client):
    admin_h = helpers.admin_headers(client)
    client.post(
        "/api/session",
        json={"section": "大陆新题", "part": "P1", "count": 2},
        headers=admin_h,
    )
    resp = client.get("/api/admin/users", headers=admin_h)
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert users[0]["username"] == "admin"
    assert users[0]["role"] == "admin"
    assert users[0]["draws_total"] == 2
    assert users[0]["draws_7d"] == 2


def test_admin_create_delete_user(client):
    admin_h = helpers.admin_headers(client)
    resp = _create_user(client, admin_h, "carol")
    assert resp.status_code == 200
    users = client.get("/api/admin/users", headers=admin_h).json()["users"]
    carol = next(u for u in users if u["username"] == "carol")
    assert client.delete(f"/api/admin/users/{carol['id']}", headers=admin_h).status_code == 200
    assert all(
        u["username"] != "carol"
        for u in client.get("/api/admin/users", headers=admin_h).json()["users"]
    )


def test_admin_cannot_delete_self(client):
    admin_h = helpers.admin_headers(client)
    boss = client.get("/api/admin/users", headers=admin_h).json()["users"][0]
    assert client.delete(f"/api/admin/users/{boss['id']}", headers=admin_h).status_code == 400


def test_admin_reset_password_revokes_sessions(client):
    admin_h = helpers.admin_headers(client)
    _create_user(client, admin_h, "bob")
    users = client.get("/api/admin/users", headers=admin_h).json()["users"]
    bob = next(u for u in users if u["username"] == "bob")
    bob_h = helpers.auth_headers(client, "bob", "secret123")
    assert client.get("/api/auth/me", headers=bob_h).status_code == 200
    resp = client.post(
        f"/api/admin/users/{bob['id']}/password",
        json={"password": "newpass456"},
        headers=admin_h,
    )
    assert resp.status_code == 200
    # 旧会话被吊销
    assert client.get("/api/auth/me", headers=bob_h).status_code == 401
    # 新密码可登录
    assert client.post(
        "/api/auth/login", json={"username": "bob", "password": "newpass456"}
    ).status_code == 200
