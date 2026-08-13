import os

import pytest

from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def test_env(tmp_path_factory):
    """Point IELTS_DB at a throwaway dir and seed admin env BEFORE main import."""
    os.environ.setdefault("IELTS_DB", str(tmp_path_factory.mktemp("dbs") / "default.db"))
    os.environ.setdefault("IELTS_ADMIN_USER", "admin")
    os.environ.setdefault("IELTS_ADMIN_PASSWORD", "secret123")
    import main  # noqa: F401  (module-level app=create_app() runs with test env)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh DB per test; admin seeded from env by create_app."""
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "fresh.db"))
    monkeypatch.setenv("IELTS_ADMIN_USER", "admin")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "secret123")
    import db
    from main import create_app

    db.init_db()
    with TestClient(create_app()) as c:
        yield c
