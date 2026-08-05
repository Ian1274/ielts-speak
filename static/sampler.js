// Pure sampling logic: no DOM, no TTS.

export function randInt(max) {
  return Math.floor(Math.random() * max);
}

const PARTS = ["P1", "P2", "P3"];

export function validateConfig(data, cfg) {
  const errors = [];
  if (!data || !data.sections || !data.sections[cfg.section]) {
    errors.push("题库数据缺失，请刷新页面重试。");
  }
  if (!PARTS.includes(cfg.part)) {
    errors.push("题型无效。");
  }
  if (!Number.isInteger(cfg.count) || cfg.count < 1 || cfg.count > 10) {
    errors.push("题目数量需为 1–10 的整数。");
  }
  if (!Number.isInteger(cfg.pauseSec) || cfg.pauseSec < 5 || cfg.pauseSec > 300) {
    errors.push("停顿时间需为 5–300 秒。");
  }
  return { ok: errors.length === 0, errors };
}

function shuffle(list) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = randInt(i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

// items:
//   P1/P3: { topic, pairedTopic, pairedPart, text }   text = one question
//   P2:    { topic, card: string[] }
export function prepareSession(data, { section, part, count }) {
  const topics = data.sections[section][part].filter((t) => {
    if (part === "P2") return t.card && t.card.length > 0;
    return t.questions && t.questions.length > 0;
  });

  if (topics.length === 0) {
    return { items: [], error: "该类别暂无可用题目。" };
  }

  if (part === "P2") {
    // 每个主题一张题卡：抽 count 个不重复主题，不足则放回补足。
    const picked = shuffle(topics);
    const items = picked.slice(0, Math.min(count, picked.length)).map((t) => ({
      topic: t.topic,
      card: t.card,
    }));
    const withReplacement = picked.length < count;
    while (items.length < count) {
      const t = picked[randInt(picked.length)];
      items.push({ topic: t.topic, card: t.card });
    }
    return { items, withReplacement };
  }

  // P1/P3：先随机选一个主题，再从该主题抽 count 个问题；不足则放回补足。
  const topic = topics[randInt(topics.length)];
  const questions = shuffle(topic.questions);
  const items = questions.slice(0, Math.min(count, questions.length)).map((text) => ({
    topic: topic.topic,
    pairedTopic: topic.paired_topic,
    pairedPart: topic.paired_part,
    text,
  }));
  const withReplacement = questions.length < count;
  while (items.length < count) {
    items.push({
      topic: topic.topic,
      pairedTopic: topic.paired_topic,
      pairedPart: topic.paired_part,
      text: questions[randInt(questions.length)],
    });
  }
  return { items, withReplacement };
}
