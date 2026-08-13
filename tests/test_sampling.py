import random
from collections import Counter

import sampling

PAYLOAD = {
    "sections": {
        "S": {
            "P1": [
                {"topic": "T1", "questions": ["q1", "q2", "q3"], "card": None,
                 "paired_topic": "T1", "paired_part": "P1"},
                {"topic": "T2", "questions": ["q4", "q5", "q6"], "card": None,
                 "paired_topic": "T2", "paired_part": "P1"},
            ],
            "P2": [
                {"topic": "C1", "questions": [], "card": ["line1"],
                 "paired_topic": "C1", "paired_part": "P2"},
                {"topic": "C2", "questions": [], "card": ["line2"],
                 "paired_topic": "C2", "paired_part": "P2"},
            ],
            "P3": [],
        }
    }
}


def test_uniform_without_history():
    rng = random.Random(42)
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, Counter(), rng)
        seen[items[0]["text"]] += 1
    # 6 题均匀:每题出现次数在 333±80 内(种子固定,稳定)
    assert min(seen.values()) > 250
    assert max(seen.values()) < 420


def test_no_duplicates_within_session():
    rng = random.Random(7)
    for _ in range(100):
        items, with_repl, _ = sampling.sample_session(PAYLOAD, "S", "P1", 3, Counter(), rng)
        texts = [i["text"] for i in items]
        assert len(texts) == len(set(texts))
        assert with_repl is False


def test_recent_question_downweighted():
    rng = random.Random(9)
    recent = Counter({"S|P1|T1|q1": 10})
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, recent, rng)
        seen[items[0]["text"]] += 1
    # q1 权重 0.25^10 ≈ 1e-6,2000 次里几乎不可能抽到
    assert seen["q1"] <= 2


def test_all_recent_falls_back_to_uniform():
    rng = random.Random(11)
    recent = Counter({f"S|P1|T{i//3+1}|q{i}": 10 for i in range(1, 7)})
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, recent, rng)
        seen[items[0]["text"]] += 1
    assert min(seen.values()) > 250


def test_replacement_when_count_exceeds_pool():
    rng = random.Random(13)
    items, with_repl, _ = sampling.sample_session(PAYLOAD, "S", "P1", 5, Counter(), rng)
    assert len(items) == 5
    assert with_repl is True


def test_p2_recent_topic_downweighted():
    rng = random.Random(17)
    recent = Counter({"S|P2|C1|None": 8})
    seen = Counter()
    for _ in range(500):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P2", 1, recent, rng)
        seen[items[0]["topic"]] += 1
    assert seen["C2"] > 400


def test_empty_section_returns_empty():
    rng = random.Random(19)
    payload = {"sections": {"S": {"P1": [], "P2": [], "P3": []}}}
    items, _, _ = sampling.sample_session(payload, "S", "P1", 2, Counter(), rng)
    assert items == ()
