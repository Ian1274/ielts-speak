"""TTS synthesis via DashScope qwen3-tts-flash (HTTP, non-realtime).

Audio is cached on disk keyed by (model, instructions, voice, rate, text)
hash, so each question is synthesized only once per voice. We use the
plain flash model (not instruct-flash): measured pitch shows
instruct-flash outputs a high, gender-muddled voice for both sexes
(Ethan 222Hz / Jennifer 263Hz), while flash keeps real male/female
timbre (Ethan 121Hz / Jennifer 193Hz). Tone instructions were dropped
for that reason; flash voices are plain by default.
"""
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

# 包位于 ielts/ 下,项目根在父目录:.env / .cache 留在仓库根
BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("IELTS_SPEAK_TTS_CACHE", str(BASE_DIR / ".cache" / "tts")))

MODEL = os.environ.get("IELTS_SPEAK_TTS_MODEL", "qwen3-tts-flash")

# 语气指令仅 instruct-flash 支持;flash 无此参数,保留常量只作缓存 key 区分,
# 未来若换回 instruct 模型时缓存自动失效。
TONE_INSTRUCTIONS = os.environ.get(
    "IELTS_SPEAK_TTS_INSTRUCTIONS",
    "Speak in a calm, gentle, plain and unhurried tone. Avoid exaggerated emotions.",
)

# qwen3-tts-flash English voices (label shown in UI).
# 实测 MaaS 业务空间:Ryan 合成音调错误(接近女声),男声用 Ethan(121Hz 正常男声)。
VOICES: dict[str, str] = {
    "Jennifer": "Jennifer · 女声 美语",
    "Ethan": "Ethan · 男声 美语",
}
# 旧选择兼容:Ryan 的音频缓存与新选择自动切到 Ethan
VOICE_ALIASES: dict[str, str] = {"Ryan": "Ethan"}
DEFAULT_VOICE = "Jennifer"


def _resolve_voice(voice: str) -> str:
    return VOICE_ALIASES.get(voice, voice)
MAX_TEXT_LEN = 500
DEFAULT_RATE = 1.0
MIN_RATE = 0.5
MAX_RATE = 2.0

# 业务空间专属域名（阿里云官方推荐）：性能和稳定性更优。
BASE_URL = os.environ.get(
    "IELTS_SPEAK_TTS_BASEURL",
    "https://llm-eizr56utguljv7y8.cn-beijing.maas.aliyuncs.com",
)
GEN_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


class TtsError(Exception):
    """Raised on synthesis failure; message is safe to show the user."""


def _load_api_key() -> str:
    """Read QWEN_APIKEY from env or .env (small local parse, no extra dep)."""
    env = os.environ.get("QWEN_APIKEY")
    if env:
        return env
    env_file = BASE_DIR / ".env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("QWEN_APIKEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    raise TtsError("未配置 QWEN_APIKEY，无法合成语音。")


def _cache_path(voice: str, rate: float, text: str) -> Path:
    voice = _resolve_voice(voice)
    digest = hashlib.sha256(f"{MODEL}:{TONE_INSTRUCTIONS}:{voice}:{rate}:{text}".encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.wav"


def _synth_remote(voice: str, text: str, rate: float) -> bytes:
    """Synthesize via qwen3-tts-flash HTTP endpoint; never caches."""
    voice = _resolve_voice(voice)
    body = json.dumps(
        {
            "model": MODEL,
            "input": {"text": text},
            "parameters": {"voice": voice, "speech_rate": rate},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + GEN_PATH,
        data=body,
        headers={
            "Authorization": f"Bearer {_load_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise TtsError(f"语音合成失败 (HTTP {exc.code})") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise TtsError("语音合成网络请求失败。") from exc

    audio_url = payload.get("output", {}).get("audio", {}).get("url")
    if not audio_url:
        raise TtsError("语音合成失败：未返回音频。")
    try:
        with urllib.request.urlopen(audio_url, timeout=60) as resp:
            return resp.read()
    except OSError as exc:
        raise TtsError("语音合成失败：音频下载失败。") from exc


def synthesize(voice: str, text: str, rate: float = DEFAULT_RATE) -> bytes:
    """Return audio bytes for (voice, rate, text); disk cache first, fill on miss."""
    path = _cache_path(voice, rate, text)
    if path.is_file():
        return path.read_bytes()

    audio = _synth_remote(voice, text, rate)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)  # immutable write: never touches existing data
    except OSError:
        pass  # cache is best-effort; serve audio anyway
    return audio


def validate(voice: str, text: str, rate: float = DEFAULT_RATE) -> str | None:
    """Return a Chinese error message, or None when valid."""
    if _resolve_voice(voice) not in VOICES:
        return "未知发音人。"
    if not MIN_RATE <= rate <= MAX_RATE:
        return f"语速需在 {MIN_RATE}–{MAX_RATE} 之间。"
    if not text or len(text) > MAX_TEXT_LEN:
        return f"文本长度需为 1–{MAX_TEXT_LEN} 字符。"
    return None
