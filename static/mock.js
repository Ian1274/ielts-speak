// 全真模拟:配置 → 入场 → P1 → P2(过渡/准备/陈述)→ P3 → 时间汇总。
// 流程与台词按 docs/mock-exam-flow-design.md(用户审定版)。

import { speakTts, speakBrowser, ensureVoices, isSupported, cancel, CancelledError } from "./speech.js";
import { fetchMe, logout, refreshAuthUI } from "./auth.js";

const $ = (id) => document.getElementById(id);

const els = {
  viewConfig: $("viewConfig"),
  viewExam: $("viewExam"),
  viewSummary: $("viewSummary"),
  chipsSection: document.querySelectorAll(".chip[data-section]"),
  chipsVoice: document.querySelectorAll(".chip[data-voice]"),
  start: $("start"),
  error: $("error"),
  partLabel: $("partLabel"),
  cuecard: $("cuecard"),
  cuecardBody: $("cuecardBody"),
  timer: $("timer"),
  hint: $("hint"),
  btnId: $("btnId"),
  btnNext: $("btnNext"),
  btnSkip: $("btnSkip"),
  btnRepeat: $("btnRepeat"),
  btnQuit: $("btnQuit"),
  quitModal: $("quitModal"),
  quitConfirm: $("quitConfirm"),
  summaryTable: $("summaryTable"),
  backHome: $("backHome"),
  authUser: $("authUser"),
  authAvatar: $("authAvatar"),
  authAdminBtn: $("authAdminBtn"),
  authLogoutBtn: $("authLogoutBtn"),
};

const s = {
  state: "config", // config | intro | p1 | p2prep | p2talk | p3 | summary
  section: "大陆新题",
  voice: "Jennifer",
  packet: null,
  scripts: null,
  sessionId: null,
  nth: 1,
  queue: [],          // 提问队列(p1First + p1Topics + p3)
  idx: 0,
  p1Total: 0,
  answered: [],       // 已作答 item_key(finish 时上报)
  durations: {},      // 各环节秒数
  stageStart: 0,
  timerId: null,
  timerDeadline: 0,
  pending: null,      // 当前等待的按键 {key, resolve}
  browserVoice: null,
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function setError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

function setActive(group, key) {
  for (const el of group) {
    const k = Object.keys(el.dataset)[0];
    el.classList.toggle("is-active", el.dataset[k] === String(key));
  }
}

function bindChips(group, onChange) {
  for (const el of group) {
    el.addEventListener("click", () => {
      const k = Object.keys(el.dataset)[0];
      onChange(el.dataset[k]);
      setActive(group, el.dataset[k]);
    });
  }
}

bindChips(els.chipsSection, (val) => {
  s.section = val;
  localStorage.setItem("ielts-mock-section", val);
});
bindChips(els.chipsVoice, (val) => {
  s.voice = val;
  localStorage.setItem("ielts-mock-voice", val);
});

// ── 按键 ───────────────────────────────────────────────────
function setActions({ id = false, next = false, skip = false, repeat = false }) {
  els.btnId.hidden = !id;
  els.btnNext.hidden = !next;
  els.btnSkip.hidden = !skip;
  els.btnRepeat.hidden = !repeat;
}

function waitAction(key) {
  return new Promise((resolve) => {
    s.pending = { key, resolve };
  });
}

function resolveAction(key) {
  if (s.pending && s.pending.key.split("|").includes(key)) {
    const { resolve } = s.pending;
    s.pending = null;
    resolve(key);
  }
}

els.btnId.addEventListener("click", () => resolveAction("id"));
els.btnNext.addEventListener("click", () => resolveAction("next"));
els.btnSkip.addEventListener("click", () => resolveAction("skip"));
els.btnRepeat.addEventListener("click", () => resolveAction("repeat"));

// ── 退出确认:页面内弹层,确认后放弃本场考试 ────────────────
function showQuitModal() {
  els.quitModal.hidden = false;
  els.quitModal.setAttribute("aria-hidden", "false");
}
function hideQuitModal() {
  els.quitModal.hidden = true;
  els.quitModal.setAttribute("aria-hidden", "true");
}

els.btnQuit.addEventListener("click", showQuitModal);
for (const el of document.querySelectorAll("[data-quit-close]")) {
  el.addEventListener("click", hideQuitModal);
}

els.quitConfirm.addEventListener("click", async () => {
  hideQuitModal();
  cancel();
  stopTimer();
  const sid = s.sessionId;
  try {
    if (sid !== null) {
      await fetch("/api/mock/finish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sid, abandoned: true }),
      });
    }
  } catch { /* 上报失败不阻塞退出 */ }
  location.href = "/";
});

// ── 考试流程 ───────────────────────────────────────────────
async function startExam() {
  setError("");
  let resp;
  try {
    resp = await fetch("/api/mock/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section: s.section, voice: s.voice }),
    });
  } catch {
    setError("网络错误,请重试。");
    return;
  }
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    setError(j.detail || "模拟开考失败,请重试。");
    return;
  }
  const body = await resp.json();

  s.packet = body.packet;
  s.scripts = body.scripts;
  s.sessionId = body.sessionId;
  s.nth = body.nth;
  s.queue = [];
  for (const q of s.packet.p1First.questions) s.queue.push({ part: "P1", ...q });
  for (const t of s.packet.p1Topics) {
    for (const q of t.questions) s.queue.push({ part: "P1", ...q });
  }
  for (const q of s.packet.p3.questions) s.queue.push({ part: "P3", ...q });
  s.idx = 0;
  s.p1Total = s.queue.filter((q) => q.part === "P1").length;
  s.answered = [];
  s.durations = {};
  s.pending = null;

  els.viewConfig.hidden = true;
  els.viewExam.hidden = false;
  els.viewSummary.hidden = true;
  els.cuecard.hidden = true;
  els.timer.hidden = true;
  els.partLabel.textContent = "入场";
  setActions({ id: true });
  els.hint.textContent = "请出示证件,开始考试";

  // 入场:自我介绍 → 出示准考证 → 点「出示身份证」进 P1
  s.state = "intro";
  s.stageStart = performance.now();
  await speak(s.scripts.opening);
  await speak(s.scripts.idCheck);
  if (s.state !== "intro") return;
  els.hint.textContent = "点击「出示身份证」进入 Part 1";
  const act = await waitAction("id");
  if (act !== "id") return;
  s.durations["入场"] = (performance.now() - s.stageStart) / 1000;
  await beginP1();
}

async function beginP1() {
  s.state = "p1";
  els.partLabel.textContent = "Part 1";
  s.stageStart = performance.now();
  const p1Items = s.queue.filter((q) => q.part === "P1");
  for (const item of p1Items) {
    if (s.state !== "p1") return;
    const act = await askQuestion(item);
    if (act === "stop") return; // next/skip 都继续循环
  }
  s.durations["P1"] = (performance.now() - s.stageStart) / 1000;
  await beginP2();
}

// 提问一轮:播放 → 等按键;重复则重播后继续等;继续记入已答,跳过不记。
async function askQuestion(item) {
  await speak(item.text);
  els.hint.textContent = "点击「继续」进入下一问,「跳过」略过此题";
  setActions({ next: true, skip: true, repeat: true });
  for (;;) {
    const act = await waitAction("next|skip|repeat");
    if (s.state === "summary") return "stop";
    if (act === "repeat") {
      await speak(item.text);
      continue;
    }
    if (act === "next") s.answered.push(item.key);
    return act;
  }
}

async function beginP2() {
  // 考官过渡语说完题卡才上屏;倒计时结束题卡消失;全程不显示字幕
  s.state = "p2prep";
  els.partLabel.textContent = "Part 2 · 准备";
  s.stageStart = performance.now();
  setActions({});
  els.hint.textContent = "考官正在说明 Part 2 要求…";
  await speak(s.scripts.p2Transition);
  if (s.state !== "p2prep") return;
  renderCuecard();
  els.hint.textContent = "1 分钟准备,可做笔记";
  await countdown(60);
  hideCuecard();
  if (s.state !== "p2prep") return;
  await speak(s.scripts.p2PrepEnd);
  if (s.state !== "p2prep") return;
  els.hint.textContent = "点击「继续」开始陈述";
  setActions({ next: true });
  const act = await waitAction("next");
  if (act !== "next") return;
  s.durations["P2 准备"] = (performance.now() - s.stageStart) / 1000;
  await beginTalk();
}

async function beginTalk() {
  // 陈述无倒计时:说完自己点「继续」进 P3
  s.state = "p2talk";
  els.partLabel.textContent = "Part 2 · 陈述";
  s.stageStart = performance.now();
  els.hint.textContent = "陈述完毕,点击「继续」进入 Part 3";
  setActions({ next: true });
  const act = await waitAction("next");
  if (act !== "next") return;
  s.durations["P2 陈述"] = (performance.now() - s.stageStart) / 1000;
  await beginP3();
}

async function beginP3() {
  s.state = "p3";
  els.partLabel.textContent = "Part 3";
  s.stageStart = performance.now();
  hideCuecard();
  const p3Items = s.queue.filter((q) => q.part === "P3");

  setActions({});
  els.hint.textContent = "考官正在过渡到 Part 3…";
  await speak(s.scripts.p3Transition);
  if (s.state !== "p3") return;
  els.hint.textContent = "……";
  await sleep(3000); // 过渡语后停顿 3 秒
  if (s.state !== "p3") return;

  for (const item of p3Items) {
    if (s.state !== "p3") return;
    const act = await askQuestion(item);
    if (act === "stop") return; // next/skip 都继续循环
  }
  s.durations["P3"] = (performance.now() - s.stageStart) / 1000;
  await beginClose();
}

async function beginClose() {
  s.state = "summary";
  els.partLabel.textContent = "结束";
  setActions({});
  await speak(s.scripts.closing);
  showSummary();
}

function renderCuecard() {
  els.cuecardBody.replaceChildren();
  for (const line of s.packet.p2.card) {
    const p = document.createElement("p");
    p.textContent = line;
    els.cuecardBody.appendChild(p);
  }
  els.cuecard.hidden = false;
  $("mockScreen").classList.add("is-cue");
}

function hideCuecard() {
  els.cuecard.hidden = true;
  $("mockScreen").classList.remove("is-cue");
}

function showSummary() {
  els.viewExam.hidden = true;
  els.viewSummary.hidden = false;
  els.summaryTable.replaceChildren();
  const rows = [
    ["P1 答题", s.durations["P1"] || 0],
    ["P2 答题", s.durations["P2 陈述"] || 0],
    ["P3 答题", s.durations["P3"] || 0],
  ];
  for (const [name, sec] of rows) {
    const tr = document.createElement("tr");
    const tdName = document.createElement("td");
    tdName.textContent = name;
    const tdSec = document.createElement("td");
    tdSec.textContent = `${sec.toFixed(1)} 秒`;
    tr.append(tdName, tdSec);
    els.summaryTable.appendChild(tr);
  }
  // 上报作答与时长;失败不影响展示
  fetch("/api/mock/finish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: s.sessionId,
      answered_keys: s.answered,
      durations: s.durations,
    }),
  }).catch(() => {});
}

els.backHome.addEventListener("click", () => {
  location.href = "/";
});

// ── 倒计时:到点停止,不自动前进 ────────────────────────────
function countdown(seconds) {
  return new Promise((resolve) => {
    els.timer.hidden = false;
    s.timerDeadline = Date.now() + seconds * 1000;
    const tick = () => {
      const remain = Math.max(0, s.timerDeadline - Date.now());
      const total = Math.ceil(remain / 1000);
      els.timer.textContent = `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
      if (remain <= 0) {
        stopTimer();
        els.timer.hidden = true;
        resolve();
        return;
      }
      s.timerId = setTimeout(tick, 250);
    };
    tick();
  });
}

function stopTimer() {
  if (s.timerId !== null) {
    clearTimeout(s.timerId);
    s.timerId = null;
  }
}

// ── 语音:服务器 TTS → 浏览器语音;不显示字幕,只听语音 ────
async function speak(text) {
  try {
    await speakTts(text, s.voice, 1.0);
    return;
  } catch (err) {
    if (err instanceof CancelledError || s.state === "summary" && s.pending === null) return;
    if (isSupported()) {
      if (!s.browserVoice) s.browserVoice = await ensureVoices(s.voice === "Jennifer" ? "female" : "male");
      if (s.browserVoice) {
        try {
          await speakBrowser(text, s.browserVoice);
          return;
        } catch { /* 落到降级提示 */ }
      }
    }
  }
  setError("语音不可用,已切换文字显示。可点「重复」重听。");
}

// ── 登录态 ─────────────────────────────────────────────────
els.authLogoutBtn.addEventListener("click", async () => {
  await logout();
  location.href = "/login.html";
});

async function initAuth() {
  const me = await fetchMe();
  if (!me) {
    location.href = "/login.html?next=/mock.html";
    return;
  }
  await refreshAuthUI(els);
}

// ── 初始化 ─────────────────────────────────────────────────
const savedSection = localStorage.getItem("ielts-mock-section");
if (savedSection) {
  s.section = savedSection;
  setActive(els.chipsSection, savedSection);
}
const savedVoice = localStorage.getItem("ielts-mock-voice");
if (savedVoice) {
  // Ryan 已由 Ethan 替代(MaaS 合成音调错误),旧选择自动迁移
  s.voice = savedVoice === "Ryan" ? "Ethan" : savedVoice;
  setActive(els.chipsVoice, s.voice);
}

els.start.addEventListener("click", () => startExam());
initAuth();
