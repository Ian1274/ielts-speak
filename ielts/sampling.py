"""Weighted sampling of the question bank, biased away from recently drawn items.

Pure logic: no I/O. `recent` is a Counter of item_key -> times drawn in the
window; weight per key is DECAY ** count, falling back to uniform when every
candidate was seen recently.
"""
from collections import Counter

DECAY = 0.25
FALLBACK_MIN_WEIGHT = 0.01


def item_key(section: str, part: str, topic: str, text: str | None) -> str:
    return f"{section}|{part}|{topic}|{text}"


def _weights(keys: list[str], recent: Counter[str]) -> list[float]:
    weights = [DECAY ** recent.get(k, 0) for k in keys]
    if weights and max(weights) < FALLBACK_MIN_WEIGHT:
        return [1.0] * len(keys)
    return weights


def _sample_no_replacement(keys, weights, count, rng):
    picked = []
    pool = list(zip(keys, weights))
    while pool and len(picked) < count:
        ks = [k for k, _ in pool]
        ws = [w for _, w in pool]
        i = rng.choices(range(len(pool)), weights=ws, k=1)[0]
        picked.append(pool[i][0])
        pool.pop(i)
    return picked


def sample_topics(payload, section, part, count, recent, rng):
    """Pick `count` distinct topics, weighted by their summed question weights.

    Returns a list of topic dicts (empty when the pool has no questions).
    Used by the mock exam for P1 topics 2 and 3.
    """
    topic_infos = []
    for t in payload["sections"][section][part]:
        questions = [q for q in t["questions"] if q]
        if not questions:
            continue
        keys = [item_key(section, part, t["topic"], q) for q in questions]
        topic_infos.append((t, sum(_weights(keys, recent))))
    if not topic_infos:
        return []
    topic_keys = [item_key(section, part, t["topic"], None) for t, _ in topic_infos]
    weights = [w for _, w in topic_infos]
    picked = _sample_no_replacement(topic_keys, weights, count, rng)
    by_key = dict(zip(topic_keys, topic_infos))
    return [by_key[k][0] for k in picked]


def sample_questions_from_topic(topic, section, part, count, recent, rng):
    """Sample `count` questions from one topic dict; returns (texts, keys).

    No replacement, refilled from the full pool when the topic holds fewer
    than `count` questions.
    """
    questions = [q for q in topic["questions"] if q]
    keys = [item_key(section, part, topic["topic"], q) for q in questions]
    weights = _weights(keys, recent)
    picked = _sample_no_replacement(keys, weights, count, rng)
    picked += [rng.choices(keys, weights=weights, k=1)[0]
               for _ in range(count - len(picked))]
    text_by_key = dict(zip(keys, questions))
    return [text_by_key[k] for k in picked], picked


def sample_session(payload, section, part, count, recent, rng):
    """Sample one session; returns (items, with_replacement, keys)."""
    topics = payload["sections"][section][part]

    if part == "P2":
        keys = [item_key(section, "P2", t["topic"], None) for t in topics]
        weights = _weights(keys, recent)
        picked = _sample_no_replacement(keys, weights, count, rng)
        picked += [rng.choices(keys, weights=weights, k=1)[0]
                   for _ in range(count - len(picked))]
        by_key = {item_key(section, "P2", t["topic"], None): t for t in topics}
        items = tuple({"topic": by_key[k]["topic"], "card": by_key[k]["card"]}
                      for k in picked)
        return items, count > len(keys), picked

    topic_infos = []
    for t in topics:
        questions = [q for q in t["questions"] if q]
        if not questions:
            continue
        keys = [item_key(section, part, t["topic"], q) for q in questions]
        weights = _weights(keys, recent)
        topic_infos.append((t, questions, keys, weights, sum(weights)))
    if not topic_infos:
        return (), False, ()

    chosen = rng.choices(topic_infos, weights=[ti[4] for ti in topic_infos], k=1)[0]
    t, questions, keys, weights, _ = chosen
    picked = _sample_no_replacement(keys, weights, count, rng)
    picked += [rng.choices(keys, weights=weights, k=1)[0]
               for _ in range(count - len(picked))]
    text_by_key = dict(zip(keys, questions))
    items = tuple(
        {"topic": t["topic"], "pairedTopic": t["paired_topic"],
         "pairedPart": t["paired_part"], "text": text_by_key[k]}
        for k in picked
    )
    return items, count > len(keys), picked
