"""Parse 2605-08-speak.md into the JSON payload served by /api/data.

Pure module: no I/O at import time, immutable dataclasses, never mutates input.
"""
import re
from dataclasses import dataclass
from pathlib import Path

SECTION_ORDER: tuple[str, ...] = ("大陆新题", "大陆老题", "非大陆新题")
PART_ORDER: tuple[str, ...] = ("P1", "P2", "P3")
PLACEHOLDER: str = "待补充"

# Defensive cleanup for PDF-extraction artifacts (see /tmp/parse_speak.py):
STRIP_HEADING_PREFIX = re.compile(r"^#+\s+")
IMAGE_LINE = re.compile(r"^!\[")
# A joined line may hold several questions; candidate split on "? "/"？ " + capital.
QUESTION_SPLIT = re.compile(r"(?<=[?？])\s+(?=[A-Z0-9])")


def _split_questions(line: str) -> tuple[str, ...]:
    """Split a joined line into standalone questions.

    A candidate split point is only taken when the remainder is itself a
    complete question: carries a terminal question mark and is long enough
    to be a full sentence (>15 chars). Short continuations like "Why and
    how?" / "Why or why not?" / "And how?" stay attached to the question
    they belong to.
    """
    pieces: list[str] = []
    start = 0
    for m in QUESTION_SPLIT.finditer(line):
        rest = line[m.end():]
        if len(rest) > 15 and ("?" in rest or "？" in rest):
            pieces.append(line[start : m.start()])
            start = m.end()
    pieces.append(line[start:])
    return tuple(p.strip() for p in pieces if p.strip())


class ParserError(Exception):
    """Raised on structural failure; message carries the offending line number."""


@dataclass(frozen=True)
class Topic:
    name: str
    part: str  # "P1" | "P2" | "P3"
    questions: tuple[str, ...]  # P1/P3; empty for P2
    card: tuple[str, ...] | None  # P2 only; None otherwise
    paired_topic: str  # canonical topic name; P3 resolves via P2 then P1
    paired_part: str  # "P2" | "P1" | "P3"


def _clean_line(raw: str) -> str:
    return STRIP_HEADING_PREFIX.sub("", raw.strip())


def parse_speak_md(path: Path) -> dict[str, dict[str, tuple[Topic, ...]]]:
    """Parse the cleaned question bank into {section: {part: (Topic, ...)}}.

    Raises ParserError with the offending line number on structural drift.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParserError(f"无法读取题库文件 {path}: {exc}") from exc

    tree: dict[str, dict[str, list[Topic]]] = {
        s: {p: [] for p in PART_ORDER} for s in SECTION_ORDER
    }
    section: str | None = None
    part: str | None = None
    pending: Topic | None = None  # current topic being filled

    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or IMAGE_LINE.match(stripped):
            continue
        if stripped == PLACEHOLDER:
            continue
        # Heading patterns matched against the raw stripped line first.
        m = re.match(r"^(#+) (.*)$", stripped)
        if m:
            level, rest = len(m.group(1)), m.group(2)
            if level == 1 and rest in SECTION_ORDER:
                section, part, pending = rest, None, None
                continue
            if section is None:
                continue
            if level == 2 and rest in PART_ORDER:
                part, pending = rest, None
                continue
            if level >= 3 and rest:
                name = rest.strip()
                if part is None:
                    raise ParserError(f"第 {lineno} 行: 主题 {name!r} 前缺少 Part 标题")
                pending = Topic(
                    name=name, part=part, questions=(), card=None,
                    paired_topic=name, paired_part=part,
                )
                tree[section][part].append(pending)
                continue
        # Content line; strip any stray heading prefix (PDF artifact).
        line = _clean_line(stripped)
        if not line or IMAGE_LINE.match(line):
            continue
        if pending is None:
            raise ParserError(f"第 {lineno} 行: 内容 {line[:30]!r} 前缺少主题标题")

        if part == "P2":
            card = pending.card if pending.card is not None else ()
            pending = Topic(
                name=pending.name, part=pending.part, questions=(),
                card=card + (line,), paired_topic=pending.name,
                paired_part=pending.part,
            )
            tree[section][part][-1] = pending
        else:
            questions = pending.questions
            for piece in _split_questions(line):
                questions = questions + (piece,)
            pending = Topic(
                name=pending.name, part=pending.part, questions=questions,
                card=None, paired_topic=pending.name, paired_part=pending.part,
            )
            tree[section][part][-1] = pending

    _resolve_p3_pairs(tree)
    _drop_empty_topics(tree)
    return {s: {p: tuple(t) for p, t in parts.items()} for s, parts in tree.items()}


def _resolve_p3_pairs(tree: dict[str, dict[str, list[Topic]]]) -> None:
    """P3 topics share the topic name with their P2 (or P1) counterpart."""
    for section, parts in tree.items():
        by_name: dict[str, tuple[str, str]] = {}
        for p in ("P2", "P1"):
            for t in parts[p]:
                by_name.setdefault(t.name, (p, t.name))
        p3 = parts["P3"]
        for i, t in enumerate(p3):
            pair_part, pair_name = by_name.get(t.name, (t.part, t.name))
            p3[i] = Topic(
                name=t.name, part=t.part, questions=t.questions, card=None,
                paired_topic=pair_name, paired_part=pair_part,
            )


def _drop_empty_topics(tree: dict[str, dict[str, list[Topic]]]) -> None:
    """Drop topics with no usable questions; also validate structure."""
    for section, parts in tree.items():
        for part, topics in parts.items():
            kept = [
                t for t in topics
                if t.questions or (t.card is not None and t.card)
            ]
            parts[part] = kept
            if not kept:
                raise ParserError(f"{section} 缺少 {part} 题目数据")


def build_payload(tree: dict[str, dict[str, tuple[Topic, ...]]]) -> dict:
    """Convert the parse tree to the /api/data JSON dict."""
    return {
        "version": 1,
        "source": "2605-08-speak.md",
        "sections": {
            section: {
                part: [
                    {
                        "topic": t.name,
                        "questions": list(t.questions),
                        "card": list(t.card) if t.card is not None else None,
                        "paired_topic": t.paired_topic,
                        "paired_part": t.paired_part,
                    }
                    for t in topics
                ]
                for part, topics in parts.items()
            }
            for section, parts in tree.items()
        },
    }
