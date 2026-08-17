// Voice playback: server TTS (Qwen) via /api/tts with browser speechSynthesis fallback.

const audioEl = new Audio();
audioEl.preload = "auto";

let pendingReject = null;

// cancel() 时用于中断正在等待的播放 Promise,区别于播放失败。
export class CancelledError extends Error {
  constructor() {
    super("已取消");
    this.name = "CancelledError";
  }
}

// ── server TTS (primary) ───────────────────────────────────
// speakTts resolves when playback ends, rejects on any failure.
export function speakTts(text, voiceId, rate = 1.0) {
  const url = `/api/tts?text=${encodeURIComponent(text)}&voice=${encodeURIComponent(voiceId)}&rate=${rate}`;
  return fetch(url)
    .then((resp) => {
      if (!resp.ok) {
        return resp.json().then(
          (j) => Promise.reject(new Error(j.detail || "语音合成失败")),
          () => Promise.reject(new Error("语音合成失败"))
        );
      }
      return resp.blob();
    })
    .then((blob) => {
      audioEl.src = URL.createObjectURL(blob);
      return new Promise((resolve, reject) => {
        pendingReject = reject;
        audioEl.onended = () => { pendingReject = null; resolve(); };
        audioEl.onerror = () => { pendingReject = null; reject(new Error("音频播放失败")); };
        audioEl.play().catch(() => { pendingReject = null; reject(new Error("音频播放失败")); });
      });
    });
}

// ── browser speechSynthesis (fallback) ─────────────────────
let voicesPromise = null;

function getVoiceList() {
  if (!("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices() || [];
}

// gender: "female" | "male" | null — 兜底时尽量匹配所选音色性别,
// 避免 TTS 失败时浏览器音色跳变(女声选 Jennifer 却听到男声)。
const GENDER_MARKERS = {
  female: ["female", "woman", "girl", "samantha", "victoria", "karen", "zira", "aria", "jenny"],
  male: ["male", "man", "boy", "daniel", "george", "david", "guy", "fred", "alex"],
};

function pickVoice(voices, gender = null) {
  const byLang = (prefix) => voices.find((v) => v.lang.toLowerCase().startsWith(prefix));
  const en = byLang("en-us") || byLang("en") || voices.find((v) => v.lang.toLowerCase().includes("en")) || null;
  if (!en || !gender) return en;
  const markers = GENDER_MARKERS[gender] || [];
  const matched = voices.find(
    (v) =>
      v.lang.toLowerCase().includes("en") &&
      markers.some((m) => v.name.toLowerCase().includes(m))
  );
  return matched || en;
}

export function isSupported() {
  return "speechSynthesis" in window;
}

export function ensureVoices(gender = null) {
  if (voicesPromise) return voicesPromise;
  voicesPromise = new Promise((resolve) => {
    const voices = getVoiceList();
    if (voices.length > 0) {
      resolve(pickVoice(voices, gender));
      return;
    }
    const onChanged = () => {
      window.speechSynthesis.removeEventListener("voiceschanged", onChanged);
      resolve(pickVoice(getVoiceList(), gender));
    };
    window.speechSynthesis.addEventListener("voiceschanged", onChanged);
    setTimeout(() => {
      window.speechSynthesis.removeEventListener("voiceschanged", onChanged);
      resolve(pickVoice(getVoiceList(), gender));
    }, 3000);
  });
  return voicesPromise;
}

export function speakBrowser(text, voice) {
  return new Promise((resolve, reject) => {
    const synth = window.speechSynthesis;
    if (!synth || !voice) {
      reject(new Error("当前浏览器不支持语音播报。"));
      return;
    }
    if (synth.speaking) {
      synth.cancel();
      setTimeout(() => startUtterance(text, voice, resolve, reject), 80);
    } else {
      startUtterance(text, voice, resolve, reject);
    }
  });
}

function startUtterance(text, voice, resolve, reject) {
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = 0.95;
  pendingReject = reject;
  u.onend = () => { pendingReject = null; resolve(); };
  u.onerror = () => { pendingReject = null; reject(new Error("语音播报中断。")); };
  window.speechSynthesis.speak(u);
}

// ── shared cancel ──────────────────────────────────────────
export function cancel() {
  audioEl.pause();
  if (audioEl.src) {
    URL.revokeObjectURL(audioEl.src);
    audioEl.removeAttribute("src");
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (pendingReject) {
    const reject = pendingReject;
    pendingReject = null;
    reject(new CancelledError());
  }
}
