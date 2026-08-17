"""Password hashing, session tokens, and admin bootstrap."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

PBKDF2_ITERATIONS = 200_000
SESSION_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(actual, expected)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + SESSION_TTL).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    conn.commit()
    return token


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def get_current_user(conn: sqlite3.Connection, token: str | None) -> dict | None:
    """Return {id, username, role} for a valid token, else None."""
    if not token:
        return None
    now = _now()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.commit()
    row = conn.execute(
        """
        SELECT u.id, u.username, u.role
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, now),
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def ensure_admin(conn: sqlite3.Connection) -> None:
    """Bootstrap admin account from env (IELTS_ADMIN_USER / IELTS_ADMIN_PASSWORD).

    Env is authoritative: a missing account is created as admin; an existing
    account with the same name is promoted to admin and its password reset
    to the env value. No-op when either env var is unset.
    """
    username = os.environ.get("IELTS_ADMIN_USER")
    password = os.environ.get("IELTS_ADMIN_PASSWORD")
    if not username or not password:
        return
    pass_hash = hash_password(password)
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES (?, ?, 'admin')",
            (username, pass_hash),
        )
    else:
        conn.execute(
            "UPDATE users SET pass_hash = ?, role = 'admin' WHERE id = ?",
            (pass_hash, row["id"]),
        )
    conn.commit()


def require_user(conn: sqlite3.Connection, token: str | None) -> dict:
    user = get_current_user(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def require_admin(conn: sqlite3.Connection, token: str | None) -> dict:
    user = require_user(conn, token)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")
    return user
