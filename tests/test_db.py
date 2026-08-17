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


def test_mock_sessions_cascades_on_user_delete():
    db.init_db()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES ('u1', 'x', 'user')"
        )
        conn.commit()
        uid = cur.lastrowid
        ms = conn.execute(
            "INSERT INTO mock_sessions (user_id, section, voice) VALUES (?, 'S', 'Ryan')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO history (user_id, section, part, topic, item_key, mode, mock_session_id) "
            "VALUES (?, 'S', 'P1', 'T', 'k', 'mock', ?)",
            (uid, ms.lastrowid),
        )
        conn.commit()
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        left = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
        left_ms = conn.execute("SELECT COUNT(*) AS n FROM mock_sessions").fetchone()["n"]
    finally:
        conn.close()
    assert left == 0
    assert left_ms == 0


def test_init_db_migrates_legacy_history_schema(tmp_path, monkeypatch):
    """v0.3.0-era history table gains mode/mock_session_id without data loss."""
    import sqlite3

    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            pass_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );
        CREATE TABLE history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            part TEXT NOT NULL,
            topic TEXT NOT NULL,
            item_key TEXT NOT NULL,
            drawn_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO users (username, pass_hash) VALUES ('u1', 'x')")
    conn.execute(
        "INSERT INTO history (user_id, section, part, topic, item_key) "
        "VALUES (1, 'S', 'P1', 'T', 'k')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("IELTS_DB", str(legacy))
    try:
        db.init_db()
        conn = db.connect()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(history)").fetchall()}
            assert {"mode", "mock_session_id"} <= cols
            row = conn.execute("SELECT * FROM history").fetchone()
            assert row["item_key"] == "k"
            assert row["mode"] == "practice"
            assert row["mock_session_id"] is None
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "mock_sessions" in tables
        finally:
            conn.close()
    finally:
        monkeypatch.undo()
