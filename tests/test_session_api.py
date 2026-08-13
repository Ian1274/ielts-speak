from collections import Counter

import db

from tests import helpers

SECTION = "大陆新题"


def test_session_anonymous_uniform_ok(client):
    resp = client.post(
        "/api/session",
        json={"section": SECTION, "part": "P1", "count": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert all({"topic", "pairedTopic", "pairedPart", "text"} <= set(i) for i in body["items"])
    assert body["withReplacement"] is False


def test_session_validation_422(client):
    assert client.post("/api/session", json={"section": "不存在", "part": "P1", "count": 2}).status_code == 422
    assert client.post("/api/session", json={"section": SECTION, "part": "P9", "count": 2}).status_code == 422
    assert client.post("/api/session", json={"section": SECTION, "part": "P1", "count": 99}).status_code == 422


def test_session_records_history_for_logged_in_user(client):
    headers = helpers.admin_headers(client)
    client.post(
        "/api/session",
        json={"section": SECTION, "part": "P1", "count": 2},
        headers=headers,
    )
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM history").fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert rows[0]["user_id"] == 1
    assert rows[0]["item_key"].startswith(f"{SECTION}|P1|")


def test_session_no_history_when_anonymous(client):
    client.post("/api/session", json={"section": SECTION, "part": "P1", "count": 2})
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
    finally:
        conn.close()
    assert n == 0


def test_session_avoids_recent_questions_when_logged_in(client):
    headers = helpers.admin_headers(client)
    seen = Counter()
    for _ in range(10):
        resp = client.post(
            "/api/session",
            json={"section": SECTION, "part": "P1", "count": 1},
            headers=headers,
        )
        seen[resp.json()["items"][0]["text"]] += 1
    # 大陆新题 P1 题库题量远大于 10,避重下重复率应低(保守断言:单一题不超过 5 次)
    assert max(seen.values()) <= 5
