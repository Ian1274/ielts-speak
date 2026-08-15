"""Parse question_bank/ md files into the JSON payload served by /api/data.

Layout: question_bank/<region>/<kind>/{p1.md, p2p3.md}

  region × kind → section name:
    mainland/new       → 大陆新题
    mainland/old       → 大陆老题
    non-mainland/new   → 非大陆新题

Each file starts with a "# <section> <part label>" header, then "## <topic>"
blocks. p1.md blocks hold questions. p2p3.md blocks hold the P2 card lines,
then a "### P3" marker followed by the topic's P3 questions; the P3 topic
shares the P2 topic name for pairing.

Pure module: no I/O at import time, immutable dataclasses, never mutates input.
"""
import re
from dataclasses import dataclass
from pathlib import Path

SECTION_ORDER: tuple[str, ...] = ("大陆新题", "大陆老题", "非大陆新题")
PART_ORDER: tuple[str, ...] = ("P1", "P2", "P3")
PLACEHOLDER: str = "待补充"
# (region, kind) → section name; files must exist for every combination.
SECTION_SOURCES: tuple[tuple[tuple[str, str], str], ...] = (
    (("mainland", "new"), "大陆新题"),
    (("mainland", "old"), "大陆老题"),
    (("non-mainland", "new"), "非大陆新题"),
)
# File name → (header part label, parts it may emit).
FILE_LAYOUT: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("p1.md", "P1", ("P1",)),
    ("p2p3.md", "P2&3", ("P2", "P3")),
)

# Defensive cleanup for PDF-extraction artifacts (see /tmp/gen_bank.py):
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
    """Raised on structural failure; message carries file and line number."""


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


def _join_questions(lines: list[str]) -> tuple[str, ...]:
    questions: tuple[str, ...] = ()
    for line in lines:
        questions = questions + _split_questions(line)
    return questions


def _parse_file(
    path: Path, section: str, part_label: str, parts: tuple[str, ...]
) -> dict[str, tuple[Topic, ...]]:
    """Parse one bank file into its topics, keyed by part.

    Raises ParserError with file name and line number on structural drift.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParserError(f"无法读取题库文件 {path}: {exc}") from exc

    lines = text.splitlines()
    header_lineno = next((i for i, s in enumerate(lines, 1) if s.strip()), 0)
    header = lines[header_lineno - 1].strip() if header_lineno else ""
    expected = f"# {section} {part_label}"
    if header != expected:
        raise ParserError(f"{path.name}: 首行标题应为 {expected!r}, 实为 {header!r}")

    topics: dict[str, list[Topic]] = {p: [] for p in parts}
    name: str | None = None
    card: list[str] = []
    questions: list[str] = []
    in_p3 = False  # content after the "### P3" marker

    def flush() -> None:
        nonlocal name, card, questions, in_p3
        if name is None:
            return
        if "P1" in parts and questions:
            topics["P1"].append(
                Topic(name=name, part="P1",
                      questions=_join_questions(questions), card=None,
                      paired_topic=name, paired_part="P1")
            )
        if "P2" in parts and card:
            topics["P2"].append(
                Topic(name=name, part="P2", questions=(),
                      card=tuple(card), paired_topic=name, paired_part="P2")
            )
        if "P3" in parts and questions:
            topics["P3"].append(
                Topic(name=name, part="P3",
                      questions=_join_questions(questions), card=None,
                      paired_topic=name, paired_part="P3")
            )
        name, card, questions, in_p3 = None, [], [], False

    for lineno, raw in enumerate(lines, 1):
        if lineno == header_lineno:
            continue
        stripped = raw.strip()
        if not stripped or IMAGE_LINE.match(stripped):
            continue
        if stripped == PLACEHOLDER:
            continue
        m = re.match(r"^(#+) (.*)$", stripped)
        if m:
            level, rest = len(m.group(1)), m.group(2).strip()
            if level == 1:
                raise ParserError(
                    f"{path.name}: 第 {lineno} 行: 不允许的额外一级标题 {stripped!r}"
                )
            if level == 2 and rest:
                flush()
                name = rest
                continue
            if level == 3 and rest == "P3" and "P3" in parts:
                if name is None:
                    raise ParserError(
                        f"{path.name}: 第 {lineno} 行: P3 标记前缺少主题标题"
                    )
                in_p3 = True
                continue
            raise ParserError(
                f"{path.name}: 第 {lineno} 行: 无法识别的标题 {stripped!r}"
            )
        if name is None:
            raise ParserError(
                f"{path.name}: 第 {lineno} 行: 内容 {stripped[:30]!r} 前缺少主题标题"
            )
        line = _clean_line(stripped)
        if not line or IMAGE_LINE.match(line):
            continue
        if "P1" in parts or in_p3:
            questions.append(line)
        else:
            card.append(line)
    flush()
    return {p: tuple(topics[p]) for p in parts}


def parse_question_bank(bank_dir: Path) -> dict[str, dict[str, tuple[Topic, ...]]]:
    """Parse the question bank directory into {section: {part: (Topic, ...)}}.

    Raises ParserError with the offending file and line on structural drift.
    """
    tree: dict[str, dict[str, tuple[Topic, ...]]] = {}
    for (region, kind), section in SECTION_SOURCES:
        merged: dict[str, tuple[Topic, ...]] = {}
        for filename, part_label, parts in FILE_LAYOUT:
            merged.update(
                _parse_file(bank_dir / region / kind / filename, section, part_label, parts)
            )
        tree[section] = merged

    _resolve_p3_pairs(tree)
    return _drop_empty_topics(tree)


def _resolve_p3_pairs(tree: dict[str, dict[str, tuple[Topic, ...]]]) -> None:
    """P3 topics share the topic name with their P2 (or P1) counterpart."""
    for section, parts in tree.items():
        by_name: dict[str, tuple[str, str]] = {}
        for p in ("P2", "P1"):
            for t in parts[p]:
                by_name.setdefault(t.name, (p, t.name))
        p3 = parts["P3"]
        parts["P3"] = tuple(
            Topic(
                name=t.name, part=t.part, questions=t.questions, card=None,
                paired_topic=by_name.get(t.name, (t.part, t.name))[1],
                paired_part=by_name.get(t.name, (t.part, t.name))[0],
            )
            for t in p3
        )


def _drop_empty_topics(
    tree: dict[str, dict[str, tuple[Topic, ...]]],
) -> dict[str, dict[str, tuple[Topic, ...]]]:
    """Drop topics with no usable questions; also validate structure."""
    cleaned: dict[str, dict[str, tuple[Topic, ...]]] = {}
    for section, parts in tree.items():
        kept_parts: dict[str, tuple[Topic, ...]] = {}
        for part, topics in parts.items():
            kept = tuple(
                t for t in topics
                if t.questions or (t.card is not None and t.card)
            )
            if not kept:
                raise ParserError(f"{section} 缺少 {part} 题目数据")
            kept_parts[part] = kept
        cleaned[section] = kept_parts
    return cleaned


def build_payload(tree: dict[str, dict[str, tuple[Topic, ...]]]) -> dict:
    """Convert the parse tree to the /api/data JSON dict."""
    return {
        "version": 1,
        "source": "question_bank",
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
