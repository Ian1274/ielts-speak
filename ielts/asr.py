"""Speech recognition via DashScope qwen3-asr-flash (synchronous, HTTP).

Audio is passed as a base64 data URL, so no public URL or OSS upload is
needed — the request goes straight to the same MaaS workspace domain as
TTS. Limits: 5 minutes / 10MB per clip, which matches IELTS answers
(per-question segments of ~20-90s).
"""
import base64
import json
import urllib.error
import urllib.request

from ielts import tts

MODEL = "qwen3-asr-flash"
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # API limit: 10MB per clip

# 兼容的录音 MIME(MediaRecorder 产物 + 常见转码格式)
MIME_WHITELIST = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/ogg;codecs=opus",
}


class AsrError(Exception):
    """Raised on transcription failure; message is safe to show the user."""


def validate_audio(audio_b64: str, mime: str) -> str | None:
    """Return a Chinese error message, or None when valid."""
    if mime not in MIME_WHITELIST:
        return "不支持的录音格式。"
    try:
        size = len(base64.b64decode(audio_b64, validate=True))
    except (ValueError, TypeError):
        return "录音数据损坏。"
    if size <= 0:
        return "录音为空。"
    if size > MAX_AUDIO_BYTES:
        return "录音超过 10MB,请缩短作答。"
    return None


def transcribe(audio_b64: str, mime: str) -> str:
    """Transcribe one audio clip; returns the English/Chinese text."""
    error = validate_audio(audio_b64, mime)
    if error:
        raise AsrError(error)

    body = json.dumps(
        {
            "model": MODEL,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"audio": f"data:{mime};base64,{audio_b64}"}
                        ],
                    }
                ]
            },
            "parameters": {"asr_options": {"enable_itn": False}},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        tts.BASE_URL + tts.GEN_PATH,
        data=body,
        headers={
            "Authorization": f"Bearer {tts._load_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise AsrError(f"语音识别失败 (HTTP {exc.code})") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AsrError("语音识别网络请求失败。") from exc

    text = (
        payload.get("output", {})
        .get("choices", [{}])[0]
        .get("message", {})
        .get("content", [{}])[0]
        .get("text")
    )
    if text is None:
        raise AsrError("语音识别失败:未返回文本。")
    return text.strip()
