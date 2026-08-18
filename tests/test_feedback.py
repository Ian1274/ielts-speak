import base64

import pytest

from ielts import asr, db, feedback
from ielts import tts

from tests import helpers


# ── stats 纯函数 ───────────────────────────────────────────

def test_stats_words_wpm_sentences():
    s = feedback.stats("I like my hometown. It is peaceful and quiet!", 12.0)
    assert s["words"] == 9
    assert s["duration_sec"] == 12.0
    assert round(s["wpm"], 1) == 45.0
    assert s["sentences"] == 2


def test_stats_empty_transcript():
    s = feedback.stats("", 5.0)
    assert s["words"] == 0
    assert s["wpm"] == 0.0
    assert s["sentences"] == 1  # 下限 1,避免除零


def test_stats_zero_duration_guarded():
    s = feedback.stats("hello world", 0)
    assert s["wpm"] == 0.0


# ── LLM 响应解析 ───────────────────────────────────────────

def test_parse_content_valid():
    data = feedback._parse_content(
        '{"scores": {"fluency": 6, "lexical": 5, "grammar": 4},'
        ' "summary": "还行", "issues": ["a"], "advice": ["b"], "model_answer": "c"}'
    )
    assert data["scores"]["fluency"] == 6


def test_parse_content_fenced_json():
    data = feedback._parse_content(
        '```json\n{"scores": {"fluency": 7, "lexical": 7, "grammar": 7},'
        ' "summary": "s", "issues": [], "advice": [], "model_answer": "m"}\n```'
    )
    assert data["scores"]["lexical"] == 7


def test_parse_content_bad_json_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_content("不是 JSON")


def test_parse_content_score_out_of_range_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_content(
            '{"scores": {"fluency": 12}, "summary": "s", "issues": [], "advice": [], "model_answer": "m"}'
        )


def test_parse_content_missing_field_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_content('{"scores": {"fluency": 5}}')


# ── 发音评分(omni 听音)──────────────────────────────────

def test_parse_pron_content_valid():
    data = feedback._parse_pron_content('{"score": 8, "reason": "发音清晰,重音准确。"}')
    assert data["score"] == 8
    assert "重音" in data["reason"]


def test_parse_pron_content_fenced():
    data = feedback._parse_pron_content(
        '```json\n{"score": 7, "reason": "语调自然。"}\n```'
    )
    assert data["score"] == 7


def test_parse_pron_content_bad_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_pron_content("不是 JSON")


def test_parse_pron_content_out_of_range_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_pron_content('{"score": 12, "reason": "x"}')


def test_parse_pron_content_missing_reason_raises():
    with pytest.raises(feedback.FeedbackError):
        feedback._parse_pron_content('{"score": 6}')


def test_pronunciation_score_omni_list_content(monkeypatch):
    # omni 模型 content 是 [{"text": ...}] 列表形态
    payload = {
        "output": {
            "choices": [{
                "message": {
                    "content": [{"text": '{"score": 7, "reason": "连读自然。"}'}]
                }
            }]
        }
    }
    monkeypatch.setattr(feedback.urllib.request, "urlopen", _fake_urlopen(payload))
    data = feedback.pronunciation_score("AAAA", "audio/webm")
    assert data == {"score": 7, "reason": "连读自然。"}


def test_pronunciation_score_http_error_raises(monkeypatch):
    def boom(req, timeout=90):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)
    import urllib.error
    monkeypatch.setattr(feedback.urllib.request, "urlopen", boom)
    with pytest.raises(feedback.FeedbackError):
        feedback.pronunciation_score("AAAA", "audio/webm")


# ── score:mock 网络层 ──────────────────────────────────────

class _FakeResp:
    def __init__(self, payload: dict):
        import json
        self._data = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def _fake_urlopen(payload):
    def fake(req, timeout=90):
        return _FakeResp(payload)
    return fake


def test_score_success(monkeypatch):
    payload = {
        "output": {
            "choices": [{
                "message": {
                    "content": '{"scores": {"fluency": 6, "lexical": 5, "grammar": 4},'
                    ' "summary": "流利但词汇单一", "issues": ["very 重复"],'
                    ' "advice": ["换词"], "model_answer": "Actually, ..."}'
                }
            }]
        }
    }
    monkeypatch.setattr(feedback.urllib.request, "urlopen", _fake_urlopen(payload))
    result = feedback.score("I very like it.", "Do you like your hometown?", "P1", 8.0)
    assert result["scores"]["grammar"] == 4
    assert result["advice"] == ["换词"]


def test_score_http_error_raises(monkeypatch):
    def boom(req, timeout=90):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)
    import urllib.error
    monkeypatch.setattr(feedback.urllib.request, "urlopen", boom)
    with pytest.raises(feedback.FeedbackError):
        feedback.score("x", "q", "P1", 1.0)


# ── asr.validate_audio ─────────────────────────────────────

def test_validate_audio():
    assert asr.validate_audio(base64.b64encode(b"x" * 100).decode(), "audio/webm") is None
    assert asr.validate_audio("!!!bad!!!", "audio/webm") is not None
    assert asr.validate_audio("", "audio/webm") is not None
    assert asr.validate_audio(base64.b64encode(b"abc").decode(), "video/mp4") is not None


# ── API 层 ─────────────────────────────────────────────────

AUDIO_B64 = base64.b64encode(b"fake audio bytes for tests").decode()


def _fake_transcribe(audio_b64, mime):
    return "I really like my hometown, it is a peaceful small city."


def _fake_score(transcript, question_text, part, duration_sec):
    return {
        "scores": {"fluency": 6, "lexical": 5, "grammar": 5},
        "summary": "整体流畅,词汇可再丰富。",
        "issues": ["very 出现多次"],
        "advice": ["用 really/quite 替换"],
        "model_answer": "My hometown is a quiet coastal town...",
    }


def _fake_pron(audio_b64, mime):
    return {"score": 7, "reason": "发音清晰,重音准确。"}


def _patch_feedback(monkeypatch):
    monkeypatch.setattr("ielts.feedback_api.asr.transcribe", _fake_transcribe)
    monkeypatch.setattr("ielts.feedback_api.feedback.score", _fake_score)
    monkeypatch.setattr("ielts.feedback_api.feedback.pronunciation_score", _fake_pron)


def _payload(**over):
    p = {
        "audio_b64": AUDIO_B64,
        "mime": "audio/webm",
        "duration_sec": 8.0,
        "part": "P1",
        "question_text": "Do you like your hometown?",
        "mode": "practice",
    }
    p.update(over)
    return p


def test_feedback_requires_login_401(client):
    resp = client.post("/api/feedback", json=_payload())
    assert resp.status_code == 401
    assert client.get("/api/feedback").status_code == 401


def test_feedback_validation_422(client):
    headers = helpers.admin_headers(client)
    for over in (
        {"part": "P9"},
        {"mode": "weird"},
        {"question_text": ""},
        {"question_text": "x" * 501},
        {"duration_sec": 0},
        {"duration_sec": 9999},
        {"audio_b64": ""},
        {"mime": "video/mp4"},
        {"audio_b64": "!!!bad!!!"},
    ):
        resp = client.post("/api/feedback", json=_payload(**over), headers=headers)
        assert resp.status_code == 422, over


def test_feedback_success_records_and_lists(client, monkeypatch):
    _patch_feedback(monkeypatch)
    headers = helpers.admin_headers(client)
    resp = client.post("/api/feedback", json=_payload(), headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["transcript"].startswith("I really like")
    assert body["scores"]["fluency"] == 6
    assert body["scores"]["pronunciation"] == 7
    assert body["pron_reason"] == "发音清晰,重音准确。"
    assert body["pron_error"] is None
    assert body["stats"]["words"] == 11

    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM feedback").fetchone()
        admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    finally:
        conn.close()
    assert row["user_id"] == admin["id"]
    assert row["part"] == "P1"
    assert row["mode"] == "practice"

    listing = client.get("/api/feedback", headers=headers).json()
    assert len(listing["items"]) == 1
    assert listing["items"][0]["question_text"] == "Do you like your hometown?"
    assert listing["items"][0]["scores"]["fluency"] == 6


def test_feedback_asr_failure_502(client, monkeypatch):
    def boom(audio_b64, mime):
        raise asr.AsrError("语音识别失败 (HTTP 400)")
    monkeypatch.setattr("ielts.feedback_api.asr.transcribe", boom)
    headers = helpers.admin_headers(client)
    resp = client.post("/api/feedback", json=_payload(), headers=headers)
    assert resp.status_code == 502
    assert "HTTP 400" in resp.json()["detail"]


def test_feedback_score_failure_502(client, monkeypatch):
    _patch_feedback(monkeypatch)

    def boom(transcript, question_text, part, duration_sec):
        raise feedback.FeedbackError("评分解析失败,请重试。")
    monkeypatch.setattr("ielts.feedback_api.feedback.score", boom)
    headers = helpers.admin_headers(client)
    resp = client.post("/api/feedback", json=_payload(), headers=headers)
    assert resp.status_code == 502


def test_feedback_pron_failure_degrades(client, monkeypatch):
    # 发音失败不整单失败:前三项照常返回,pron_error 标记
    _patch_feedback(monkeypatch)

    def boom(audio_b64, mime):
        raise feedback.FeedbackError("发音评分服务失败 (HTTP 500)")
    monkeypatch.setattr("ielts.feedback_api.feedback.pronunciation_score", boom)
    headers = helpers.admin_headers(client)
    resp = client.post("/api/feedback", json=_payload(), headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["scores"]["fluency"] == 6
    assert "pronunciation" not in body["scores"]
    assert body["pron_error"] == "发音评分服务失败 (HTTP 500)"


# ── 真实链路冒烟(有 key/网络才跑,失败跳过)─────────────

def test_live_transcribe_and_score():
    """tts 产 wav → ASR 转写 → LLM 评分。TTS/ASR/评分任一不可用则跳过。"""
    try:
        audio = tts.synthesize("Jennifer", "My hometown is a small city, and I like it a lot because it is peaceful.")
    except tts.TtsError as exc:
        pytest.skip(f"TTS 不可用: {exc}")
    b64 = base64.b64encode(audio).decode()
    try:
        text = asr.transcribe(b64, "audio/wav")
    except asr.AsrError as exc:
        pytest.skip(f"ASR 不可用: {exc}")
    assert text.strip()
    try:
        result = feedback.score(text, "Where is your hometown?", "P1", 8.0)
    except feedback.FeedbackError as exc:
        pytest.skip(f"评分不可用: {exc}")
    assert 1 <= result["scores"]["fluency"] <= 9
    try:
        pron = feedback.pronunciation_score(b64, "audio/wav")
    except feedback.FeedbackError as exc:
        pytest.skip(f"发音评分不可用: {exc}")
    assert 1 <= pron["score"] <= 9
    assert pron["reason"]
