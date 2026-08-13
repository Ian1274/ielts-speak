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
