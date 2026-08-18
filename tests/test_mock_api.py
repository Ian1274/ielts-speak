from collections import Counter

from ielts import db

from tests import helpers

SECTION = "大陆新题"
VOICE = "Ethan"


def create_session(client, headers, section=SECTION, voice=VOICE):
    resp = client.post(
        "/api/mock/session", json={"section": section, "voice": voice}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def all_keys(packet):
    keys = [q["key"] for q in packet["p1First"]["questions"]]
    for t in packet["p1Topics"]:
        keys += [q["key"] for q in t["questions"]]
    keys.append(packet["p2"]["key"])
    keys += [q["key"] for q in packet["p3"]["questions"]]
    return keys


def test_mock_session_requires_login_401(client):
    resp = client.post("/api/mock/session", json={"section": SECTION, "voice": VOICE})
    assert resp.status_code == 401
    resp = client.post("/api/mock/finish", json={"session_id": 1})
    assert resp.status_code == 401


def test_mock_session_packet_shape(client):
    body = create_session(client, helpers.admin_headers(client))
    packet = body["packet"]
    # P1 第一主题:固定首问 + 追加 1 问
    assert len(packet["p1First"]["questions"]) == 2
    assert packet["p1First"]["topic"] in ("Work or studies", "Hometown")
    # 第二、三主题:2 个不同主题 × 每主题固定 2 问
    assert len(packet["p1Topics"]) == 2
    assert packet["p1Topics"][0]["topic"] != packet["p1Topics"][1]["topic"]
    assert all(len(t["questions"]) == 2 for t in packet["p1Topics"])
    # P2 题卡
    assert packet["p2"]["card"]
    # P3:3-4 问且主题与 P2 一致
    assert 3 <= len(packet["p3"]["questions"]) <= 4
    assert packet["p3"]["topic"] == packet["p2"]["topic"]
    # 脚本齐全,首次考试 nth = 1
    for key in ("opening", "idCheck", "p2Transition", "p2PrepEnd", "p3Transition", "closing"):
        assert body["scripts"][key]
    assert body["nth"] == 1
    assert "{n}" not in body["scripts"]["opening"]


def test_mock_session_validation_422(client):
    headers = helpers.admin_headers(client)
    assert client.post(
        "/api/mock/session", json={"section": "不存在", "voice": VOICE}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/mock/session", json={"section": SECTION, "voice": "没人"}, headers=headers
    ).status_code == 422


def test_finish_records_only_answered_keys(client):
    headers = helpers.admin_headers(client)
    body = create_session(client, headers)
    keys = all_keys(body["packet"])
    answered = keys[:4]
    resp = client.post(
        "/api/mock/finish",
        json={"session_id": body["sessionId"], "answered_keys": answered, "durations": {"P1": 12.5}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] == 4
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM history").fetchall()
        sess = conn.execute("SELECT * FROM mock_sessions").fetchone()
    finally:
        conn.close()
    assert len(rows) == 4
    assert all(r["mode"] == "mock" for r in rows)
    assert all(r["mock_session_id"] == body["sessionId"] for r in rows)
    assert {r["item_key"] for r in rows} == set(answered)
    assert sess["status"] == "completed"
    assert sess["durations_json"] == '{"P1": 12.5}'


def test_finish_idempotent(client):
    headers = helpers.admin_headers(client)
    body = create_session(client, headers)
    payload = {"session_id": body["sessionId"], "answered_keys": all_keys(body["packet"])}
    first = client.post("/api/mock/finish", json=payload, headers=headers)
    assert first.json()["recorded"] > 0
    second = client.post("/api/mock/finish", json=payload, headers=headers)
    assert second.json() == {"ok": True, "already": True}
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
    finally:
        conn.close()
    assert n == len(all_keys(body["packet"]))


def test_finish_unknown_keys_ignored(client):
    headers = helpers.admin_headers(client)
    body = create_session(client, headers)
    resp = client.post(
        "/api/mock/finish",
        json={"session_id": body["sessionId"], "answered_keys": ["不存在|key"]},
        headers=headers,
    )
    assert resp.json()["recorded"] == 0
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"] == 0
    finally:
        conn.close()


def test_abandon_records_no_history(client):
    headers = helpers.admin_headers(client)
    body = create_session(client, headers)
    resp = client.post(
        "/api/mock/finish",
        json={"session_id": body["sessionId"], "abandoned": True},
        headers=headers,
    )
    assert resp.json() == {"ok": True, "abandoned": True}
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"] == 0
        status = conn.execute(
            "SELECT status FROM mock_sessions WHERE id = ?", (body["sessionId"],)
        ).fetchone()["status"]
    finally:
        conn.close()
    assert status == "abandoned"
    # 弃考不计入第 N 次
    assert create_session(client, headers)["nth"] == 1


def test_nth_counts_completed_sessions(client):
    headers = helpers.admin_headers(client)
    body1 = create_session(client, headers)
    assert body1["nth"] == 1
    client.post(
        "/api/mock/finish",
        json={"session_id": body1["sessionId"], "answered_keys": []},
        headers=headers,
    )
    body2 = create_session(client, headers)
    assert body2["nth"] == 2


def test_finish_wrong_user_404(client):
    headers = helpers.admin_headers(client)
    body = create_session(client, headers)
    client.post(
        "/api/admin/users",
        json={"username": "other_user", "password": "pass12345"},
        headers=headers,
    )
    other = helpers.auth_headers(client, "other_user", "pass12345")
    resp = client.post(
        "/api/mock/finish", json={"session_id": body["sessionId"]}, headers=other
    )
    assert resp.status_code == 404


def test_mock_p2_card_shares_avoidance_with_practice(client):
    """P2 卡参与 7 天避重:P2 池足够大时,连续场次重复率应低。"""
    headers = helpers.admin_headers(client)
    payload = client.get("/api/data", headers=headers).json()
    pool = len(payload["sections"][SECTION]["P2"])
    if pool < 6:
        return  # 池太小,跳过严格断言
    seen = Counter()
    for _ in range(10):
        body = create_session(client, headers)
        client.post(
            "/api/mock/finish",
            json={"session_id": body["sessionId"], "answered_keys": [body["packet"]["p2"]["key"]]},
            headers=headers,
        )
        seen[body["packet"]["p2"]["key"]] += 1
    assert max(seen.values()) <= 5
