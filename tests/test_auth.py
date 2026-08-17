import pytest

from ielts import db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Per-test DB so username collisions across tests never interfere."""
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "auth.db"))
    db.init_db()


def _make_user(username="alice", role="user", password="secret123"):
    from ielts import auth
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES (?, ?, ?)",
            (username, auth.hash_password(password), role),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_hash_verify_roundtrip():
    from ielts import auth
    stored = auth.hash_password("secret123")
    assert stored.startswith("pbkdf2$")
    assert auth.verify_password("secret123", stored) is True
    assert auth.verify_password("wrong", stored) is False


def test_verify_malformed_storage_returns_false():
    from ielts import auth
    assert auth.verify_password("x", "not-a-hash") is False
    assert auth.verify_password("x", "pbkdf2$zz$zz") is False


def test_hash_is_salted():
    from ielts import auth
    assert auth.hash_password("same") != auth.hash_password("same")


def test_session_roundtrip():
    from ielts import auth
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        user = auth.get_current_user(conn, token)
        assert user is not None
        assert user["username"] == "alice"
        assert user["role"] == "user"
        auth.delete_session(conn, token)
        assert auth.get_current_user(conn, token) is None
    finally:
        conn.close()


def test_expired_session_rejected():
    from ielts import auth
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        conn.execute(
            "UPDATE sessions SET expires_at = '2000-01-01 00:00:00' WHERE token = ?",
            (token,),
        )
        conn.commit()
        assert auth.get_current_user(conn, token) is None
        n = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        assert n == 0
    finally:
        conn.close()


def test_require_admin_forbids_user_role():
    from ielts import auth
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        try:
            auth.require_admin(conn, token)
            assert False, "expected 403"
        except auth.HTTPException as exc:
            assert exc.status_code == 403
    finally:
        conn.close()


def test_require_user_rejects_missing_token():
    from ielts import auth
    conn = db.connect()
    try:
        try:
            auth.require_user(conn, None)
            assert False, "expected 401"
        except auth.HTTPException as exc:
            assert exc.status_code == 401
    finally:
        conn.close()


def test_ensure_admin_creates_from_env(monkeypatch):
    from ielts import auth
    monkeypatch.setenv("IELTS_ADMIN_USER", "root")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "rootpass1")
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        row = conn.execute("SELECT * FROM users WHERE username = 'root'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["role"] == "admin"
    assert auth.verify_password("rootpass1", row["pass_hash"])


def test_ensure_admin_upserts_existing_user(monkeypatch):
    from ielts import auth
    monkeypatch.setenv("IELTS_ADMIN_USER", "ian1274")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "newpass1")
    uid = _make_user(username="ian1274", role="user", password="oldpass1")
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    finally:
        conn.close()
    assert row["role"] == "admin"
    assert auth.verify_password("newpass1", row["pass_hash"])
    assert not auth.verify_password("oldpass1", row["pass_hash"])


def test_ensure_admin_noop_without_env(monkeypatch):
    from ielts import auth
    monkeypatch.delenv("IELTS_ADMIN_USER", raising=False)
    monkeypatch.delenv("IELTS_ADMIN_PASSWORD", raising=False)
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    finally:
        conn.close()
    assert n == 0
