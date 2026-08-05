import { validateConfig, prepareSession } from "./sampler.js";
import { speakTts, speakBrowser, ensureVoices, isSupported, cancel } from "./speech.js";

const $ = (id) => document.getElementById(id);

const els = {
  tabs: document.querySelectorAll(".tab"),
  config: $("config"),
  session: $("session"),
  start: $("start"),
  stop: $("stop"),
  again: $("again"),
  backToConfig: $("backToConfig"),
  error: $("error"),
  chipsSection: document.querySelectorAll(".chip[data-section]"),
  chipsCount: document.querySelectorAll(".chip[data-count]"),
  chipsPause: document.querySelectorAll(".chip[data-pause]"),
  chipsRate: document.querySelectorAll(".chip[data-rate]"),
  countCustom: $("countCustom"),
  pauseCustom: $("pauseCustom"),
  voiceSelect: $("voiceSelect"),
  progress: $("progress"),
  clock: $("clock"),
  clockNote: $("clockNote"),
  dial: $("dial"),
  dialTicks: $("dialTicks"),
  dialNums: $("dialNums"),
  dialHand: $("dialHand"),
  hand: null,
  card: $("card"),
  cardMeta: $("cardMeta"),
  cardBody: $("cardBody"),
  toggleCard: $("toggleCard"),
  replay: $("replay"),
  doneLine: $("doneLine"),
  doneCount: $("doneCount"),
};

const session = {
  state: "idle", // idle | running | finished
  part: "P1",
  section: "大陆新题",
  items: [],
  index: 0,
  pauseMs: 120000,
  rate: 1.0,
  cancelled: false,
  timerId: null,
  voice: "Cherry",
  browserVoice: null,
  cardVisible: false,
  topicVisible: false,
};

let data = null;

function setError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

function setActive(group, key) {
  for (const el of group) {
    el.classList.toggle("is-active", el.dataset[Object.keys(el.dataset)[0]] === String(key));
  }
}

function bindChips(group, onChange) {
  for (const el of group) {
    el.addEventListener("click", () => {
      const key = Object.keys(el.dataset)[0];
      onChange(key, el.dataset[key]);
    });
  }
}

bindChips(els.chipsSection, (key, val) => {
  session.section = val;
  setActive(els.chipsSection, val);
});
bindChips(els.chipsCount, (key, val) => {
  els.countCustom.value = val;
  setActive(els.chipsCount, val);
});
bindChips(els.chipsPause, (key, val) => {
  els.pauseCustom.value = val;
  setActive(els.chipsPause, val);
});
bindChips(els.chipsRate, (key, val) => {
  session.rate = Number.parseFloat(val);
  setActive(els.chipsRate, val);
});

els.countCustom.addEventListener("input", () => setActive(els.chipsCount, null));
els.pauseCustom.addEventListener("input", () => setActive(els.chipsPause, null));

els.voiceSelect.addEventListener("change", () => {
  session.voice = els.voiceSelect.value;
  localStorage.setItem("ielts-voice", els.voiceSelect.value);
});

for (const tab of els.tabs) {
  tab.addEventListener("click", () => switchPart(tab.dataset.part));
}

function switchPart(part) {
  if (session.state === "running") return; // 会话中不允许切换题型
  session.part = part;
  for (const tab of els.tabs) {
    const active = tab.dataset.part === part;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  els.clockNote.textContent = part === "P2"
    ? "阅读题卡，计时结束进入下一题。"
    : "听题，然后开口作答，计时结束进入下一题。";
}

function showConfig() {
  els.config.hidden = false;
  els.session.hidden = true;
  session.state = "idle";
}

function categoryLine(part, item) {
  if (part === "P2") return `${session.section} · P2 · ${item.topic}`;
  return `${session.section} · ${part} · ${item.pairedTopic}`;
}

function renderItem(item) {
  session.index += 1;
  els.progress.textContent = `第 ${session.index} / ${session.items.length} 题`;
  // 切题即重置计时显示：播报期间就应看到满格倒计时，而不是上一题的残留值
  els.clock.textContent = String(Math.ceil(session.pauseMs / 1000));
  els.clock.classList.remove("clock--urgent");
  els.dial.classList.remove("dial--urgent");
  els.hand.setAttribute("transform", "rotate(0 100 100)");
  els.cardMeta.textContent = categoryLine(session.part, item);
  els.cardBody.replaceChildren();
  if (session.part === "P2") {
    for (const line of item.card) {
      const p = document.createElement("p");
      p.textContent = line;
      els.cardBody.appendChild(p);
    }
    // P2：英文题卡一开始就显示；中文主题默认隐藏，点“显示主题”才出现
    els.card.hidden = false;
    els.cardMeta.hidden = !session.topicVisible;
  } else {
    // 主题行（P1 英文 / P3 中文）+ 英文题目
    const t = document.createElement("p");
    t.className = "card__topic";
    t.textContent = item.topic;
    els.cardBody.appendChild(t);
    const p = document.createElement("p");
    p.textContent = item.text;
    els.cardBody.appendChild(p);
    els.card.hidden = !session.cardVisible;
  }
}

els.toggleCard.addEventListener("click", () => {
  const item = session.items[session.index - 1];
  if (session.part === "P2") {
    // P2：只控制中文主题的显隐，英文题卡常显
    session.topicVisible = !session.topicVisible;
    els.toggleCard.textContent = session.topicVisible ? "隐藏主题" : "显示主题";
    els.toggleCard.setAttribute("aria-pressed", String(session.topicVisible));
    if (item) els.cardMeta.hidden = !session.topicVisible;
  } else {
    session.cardVisible = !session.cardVisible;
    els.toggleCard.textContent = session.cardVisible ? "隐藏题目" : "查看题目";
    els.toggleCard.setAttribute("aria-pressed", String(session.cardVisible));
    if (item && session.state !== "idle") els.card.hidden = !session.cardVisible;
  }
});

// P1/P3：喇叭重听当前题
els.replay.addEventListener("click", () => {
  if (session.state !== "running" || session.part === "P2") return;
  const item = session.items[session.index - 1];
  if (!item) return;
  cancel();
  speakQuestion(item.text);
});

els.stop.addEventListener("click", () => {
  cancel();
  stopTimer();
  session.cancelled = true;
  showConfig();
});

els.again.addEventListener("click", () => {
  startSession();
});

els.backToConfig.addEventListener("click", () => {
  showConfig();
});

els.start.addEventListener("click", () => startSession());

async function startSession() {
  setError("");
  if (!data) {
    try {
      data = await (await fetch("/api/data")).json();
    } catch (err) {
      setError("题库加载失败，请检查网络后重试。");
      return;
    }
  }

  const count = Number.parseInt(els.countCustom.value, 10);
  const pauseSec = Number.parseInt(els.pauseCustom.value, 10);
  const cfg = { section: session.section, part: session.part, count, pauseSec, rate: session.rate };
  const v = validateConfig(data, cfg);
  if (!v.ok) {
    setError(v.errors.join(" "));
    return;
  }

  const prep = prepareSession(data, cfg);
  if (prep.error) {
    setError(prep.error);
    return;
  }

  session.state = "running";
  session.items = prep.items;
  session.index = 0;
  session.pauseMs = pauseSec * 1000;
  session.cancelled = false;
  session.cardVisible = false;
  session.topicVisible = false;
  els.toggleCard.textContent = session.part === "P2" ? "显示主题" : "查看题目";
  els.card.hidden = false;
  els.cardMeta.hidden = true;
  els.replay.hidden = session.part === "P2";

  els.config.hidden = true;
  els.session.hidden = false;
  els.again.hidden = true;
  els.backToConfig.hidden = true;
  els.doneLine.hidden = true;
  els.stop.hidden = false;
  els.toggleCard.hidden = false;

  if (prep.withReplacement) {
    setError("该主题题目不足设定数量，已按规则重复抽取。");
  }

  await runSequence();
}

async function runSequence() {
  if (session.part !== "P2") {
    if (!session.voice && isSupported()) session.voice = await ensureVoices();
  }

  for (const item of session.items) {
    if (session.cancelled) break;
    renderItem(item);
    if (session.part !== "P2") {
      await speakQuestion(item.text);
      if (session.cancelled) break;
    }
    await countdown();
    if (session.cancelled) break;
  }
  if (!session.cancelled) finishSession();
}

// 语音链路：服务器 TTS → 浏览器语音 → 文字显示
async function speakQuestion(text) {
  try {
    await speakTts(text, session.voice || "Cherry", session.rate);
    return;
  } catch (err) {
    if (session.cancelled) return;
    if (isSupported()) {
      if (!session.browserVoice) session.browserVoice = await ensureVoices();
      if (session.browserVoice) {
        try {
          await speakBrowser(text, session.browserVoice);
          return;
        } catch (err2) {
          if (session.cancelled) return;
        }
      }
    }
  }
  session.cardVisible = true;
  els.card.hidden = false;
  els.toggleCard.textContent = "隐藏题目";
  setError("语音不可用，已切换到文字显示。");
}

function countdown() {
  return new Promise((resolve) => {
    const startSec = session.pauseMs / 1000;
    const deadline = Date.now() + session.pauseMs;
    const tick = () => {
      const remain = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      els.clock.textContent = String(remain);
      // 指针一圈 = 一题作答时长，与考场挂钟同构
      els.hand.setAttribute("transform", `rotate(${(1 - remain / startSec) * 360} 100 100)`);
      els.clock.classList.toggle("clock--urgent", remain <= 10 && remain > 0);
      els.dial.classList.toggle("dial--urgent", remain <= 10 && remain > 0);
      if (remain <= 0) {
        stopTimer();
        resolve();
      }
    };
    tick();
    session.timerId = setInterval(tick, 200);
  });
}

function stopTimer() {
  if (session.timerId !== null) {
    clearInterval(session.timerId);
    session.timerId = null;
  }
}

function finishSession() {
  stopTimer();
  session.state = "finished";
  els.clock.textContent = "0";
  els.clock.classList.remove("clock--urgent");
  els.dial.classList.remove("dial--urgent");
  els.doneCount.textContent = String(session.items.length);
  els.doneLine.hidden = false;
  els.again.hidden = false;
  els.backToConfig.hidden = false;
  els.stop.hidden = true;
  els.toggleCard.hidden = true;
  els.replay.hidden = true;
  els.progress.textContent = "本轮完成";
  els.clockNote.textContent = "再次开始会重新随机抽题。";
}

switchPart("P1");

initDial();
loadVoices();

// 考场挂钟表盘：60 刻度（每 5 分钟加粗）+ 12/3/6/9 数字 + 一根指针
function initDial() {
  const NS = "http://www.w3.org/2000/svg";
  for (let i = 0; i < 60; i++) {
    const a = (i * 6 * Math.PI) / 180;
    const major = i % 5 === 0;
    const r1 = major ? 76 : 82;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", String(100 + r1 * Math.sin(a)));
    line.setAttribute("y1", String(100 - r1 * Math.cos(a)));
    line.setAttribute("x2", String(100 + 90 * Math.sin(a)));
    line.setAttribute("y2", String(100 - 90 * Math.cos(a)));
    line.setAttribute("class", major ? "dial__tick dial__tick--major" : "dial__tick");
    els.dialTicks.appendChild(line);
  }
  for (const [num, x, y] of [[12, 100, 33], [3, 167, 105], [6, 100, 177], [9, 33, 105]]) {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", String(x));
    t.setAttribute("y", String(y));
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("class", "dial__num");
    t.textContent = String(num);
    els.dialNums.appendChild(t);
  }
  const hand = document.createElementNS(NS, "line");
  hand.setAttribute("x1", "100");
  hand.setAttribute("y1", "114");
  hand.setAttribute("x2", "100");
  hand.setAttribute("y2", "40");
  els.dialHand.appendChild(hand);
  els.hand = hand;
}

async function loadVoices() {
  try {
    const resp = await fetch("/api/voices");
    if (!resp.ok) throw new Error("voices api failed");
    const { voices } = await resp.json();
    if (!voices.length) {
      els.voiceSelect.hidden = true;
      return;
    }
    els.voiceSelect.replaceChildren();
    for (const v of voices) {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.label;
      els.voiceSelect.appendChild(opt);
    }
    const saved = localStorage.getItem("ielts-voice");
    session.voice = voices.some((v) => v.id === saved) ? saved : voices[0].id;
    els.voiceSelect.value = session.voice;
  } catch (err) {
    els.voiceSelect.hidden = true;
  }
}
