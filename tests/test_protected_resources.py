from tests import helpers


def test_data_requires_login(client):
    assert client.get("/api/data").status_code == 401
    resp = client.get("/api/data", headers=helpers.admin_headers(client))
    assert resp.status_code == 200
    assert "sections" in resp.json()


def test_voices_requires_login(client):
    assert client.get("/api/voices").status_code == 401
    resp = client.get("/api/voices", headers=helpers.admin_headers(client))
    assert resp.status_code == 200
    assert isinstance(resp.json()["voices"], list)


def test_tts_requires_login(client):
    assert client.get("/api/tts", params={"text": "hello"}).status_code == 401
    # 登录后走到参数校验/合成阶段,422 说明鉴权已通过
    resp = client.get(
        "/api/tts",
        params={"text": "hello", "voice": "不存在的声音"},
        headers=helpers.admin_headers(client),
    )
    assert resp.status_code == 422
