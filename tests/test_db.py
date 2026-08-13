import sqlite3

import pytest

import db


def test_init_db_creates_tables():
    db.init_db()
    conn = db.connect()
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    assert {"users", "sessions", "history"} <= names


def test_foreign_keys_enforced():
    db.init_db()
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) "
                "VALUES ('t', 999, '2030-01-01 00:00:00')"
            )
    finally:
        conn.close()


def test_history_cascades_on_user_delete():
    db.init_db()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES ('u1', 'x', 'user')"
        )
        conn.commit()
        uid = cur.lastrowid
        conn.execute(
            "INSERT INTO history (user_id, section, part, topic, item_key) "
            "VALUES (?, 'S', 'P1', 'T', 'k')",
            (uid,),
        )
        conn.commit()
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        left = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
    finally:
        conn.close()
    assert left == 0
