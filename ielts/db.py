"""SQLite storage for users, sessions, and practice history.

Connections are short-lived (opened per call). Schema is initialized once
at startup via init_db(). Path overridable via IELTS_DB env var.
"""
import os
import sqlite3
from pathlib import Path

# 包位于 ielts/ 下,项目根在父目录:ielts.db 留在仓库根
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = BASE_DIR / "ielts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    pass_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mock_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    voice TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    durations_json TEXT,
    drawn_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_mock_sessions_user ON mock_sessions(user_id);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    part TEXT NOT NULL,
    topic TEXT NOT NULL,
    item_key TEXT NOT NULL,
    drawn_at TEXT NOT NULL DEFAULT (datetime('now')),
    mode TEXT NOT NULL DEFAULT 'practice',
    mock_session_id INTEGER NULL REFERENCES mock_sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_history_user_time ON history(user_id, drawn_at);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'practice',
    part TEXT NOT NULL,
    question_text TEXT NOT NULL,
    transcript TEXT NOT NULL,
    duration_sec REAL NOT NULL,
    scores_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id, created_at);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Upgrade legacy DBs in place: add history columns introduced in v0.4.0.

    CREATE TABLE IF NOT EXISTS does not add columns to existing tables, so
    new columns are added with ALTER TABLE when missing (idempotent).
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(history)").fetchall()}
    if "mode" not in cols:
        conn.execute(
            "ALTER TABLE history ADD COLUMN mode TEXT NOT NULL DEFAULT 'practice'"
        )
    if "mock_session_id" not in cols:
        conn.execute("ALTER TABLE history ADD COLUMN mock_session_id INTEGER NULL")
    mcols = {r["name"] for r in conn.execute("PRAGMA table_info(mock_sessions)").fetchall()}
    if mcols and "drawn_json" not in mcols:
        conn.execute("ALTER TABLE mock_sessions ADD COLUMN drawn_json TEXT")


def get_db_path() -> Path:
    return Path(os.environ.get("IELTS_DB", str(DEFAULT_DB)))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
