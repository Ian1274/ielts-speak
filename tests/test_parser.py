"""Parser tests: question_bank dir layout, structural validation, pairing."""
from pathlib import Path

import pytest

from ielts.parser import (
    ParserError,
    SECTION_SOURCES,
    FILE_LAYOUT,
    build_payload,
    parse_question_bank,
    _parse_file,
    _split_questions,
)

BANK = Path(__file__).resolve().parent.parent / "question_bank"


def test_expected_counts():
    tree = parse_question_bank(BANK)
    assert {
        s: {p: len(t) for p, t in parts.items()}
        for s, parts in tree.items()
    } == {
        "大陆新题": {"P1": 16, "P2": 29, "P3": 29},
        "大陆老题": {"P1": 22, "P2": 27, "P3": 27},
        "非大陆新题": {"P1": 8, "P2": 8, "P3": 8},
    }


def test_p2_cards_and_p1p3_questions():
    tree = parse_question_bank(BANK)
    for parts in tree.values():
        for t in parts["P2"]:
            assert t.card is not None and t.card, f"P2 题卡为空: {t.name}"
            assert not t.questions
        for p in ("P1", "P3"):
            for t in parts[p]:
                assert t.questions, f"{p} 题目无问题: {t.name}"
                assert t.card is None


def test_p3_pairs_with_p2_topic():
    tree = parse_question_bank(BANK)
    for section, parts in tree.items():
        names = {t.name for t in parts["P2"]} | {t.name for t in parts["P1"]}
        for t in parts["P3"]:
            assert t.name in names, f"{section} P3 {t.name} 无 P2/P1 同名主题"
            assert t.paired_topic == t.name


def test_p2p3_files_pair_every_p3_with_p2():
    """Every P3 block in p2p3.md shares its topic's P2 card name."""
    tree = parse_question_bank(BANK)
    for section, parts in tree.items():
        assert {t.name for t in parts["P3"]} == {t.name for t in parts["P2"]}, section


def test_build_payload_serializable():
    payload = build_payload(parse_question_bank(BANK))
    assert payload["source"] == "question_bank"
    assert payload["version"] == 1
    import json

    json.dumps(payload)


def _write_part(tmp_path: Path, header: str, body: str) -> Path:
    d = tmp_path / "mainland" / "new"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "p1.md"
    f.write_text(f"{header}\n\n{body}", encoding="utf-8")
    return f


def test_header_mismatch_raises(tmp_path):
    f = _write_part(tmp_path, "# 大陆老题 P1", "## T\n\nQ?\n")
    with pytest.raises(ParserError, match="首行标题"):
        _parse_file(f, "大陆新题", "P1", ("P1",))


def test_extra_h1_raises(tmp_path):
    f = _write_part(tmp_path, "# 大陆新题 P1", "## T\n\nQ?\n\n# stray\n")
    with pytest.raises(ParserError, match="额外一级标题"):
        _parse_file(f, "大陆新题", "P1", ("P1",))


def test_content_before_topic_raises(tmp_path):
    f = _write_part(tmp_path, "# 大陆新题 P1", "Q?\n")
    with pytest.raises(ParserError, match="缺少主题标题"):
        _parse_file(f, "大陆新题", "P1", ("P1",))


def test_p3_marker_before_topic_raises(tmp_path):
    d = tmp_path / "mainland" / "new"
    d.mkdir(parents=True)
    f = d / "p2p3.md"
    f.write_text("# 大陆新题 P2&3\n\n### P3\n\nQ?\n", encoding="utf-8")
    with pytest.raises(ParserError, match="P3 标记前缺少主题标题"):
        _parse_file(f, "大陆新题", "P2&3", ("P2", "P3"))


def test_p2p3_split_into_two_topics(tmp_path):
    d = tmp_path / "mainland" / "new"
    d.mkdir(parents=True)
    f = d / "p2p3.md"
    f.write_text(
        "# 大陆新题 P2&3\n\n"
        "## 主题A\n\n"
        "### P2\n\n"
        "Describe a thing\n"
        "You should say:\n"
        "What it is\n"
        "\n### P3\n\n"
        "Why do people like it?\n",
        encoding="utf-8",
    )
    topics = _parse_file(f, "大陆新题", "P2&3", ("P2", "P3"))
    assert [t.name for t in topics["P2"]] == ["主题A"]
    assert topics["P2"][0].card == ("Describe a thing", "You should say:", "What it is")
    assert topics["P3"][0].questions == ("Why do people like it?",)


def test_p2p3_content_before_marker_raises(tmp_path):
    d = tmp_path / "mainland" / "new"
    d.mkdir(parents=True)
    f = d / "p2p3.md"
    f.write_text("# 大陆新题 P2&3\n\n## 主题A\n\nDescribe a thing\n", encoding="utf-8")
    with pytest.raises(ParserError, match="缺少 P2/P3 标记"):
        _parse_file(f, "大陆新题", "P2&3", ("P2", "P3"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ParserError, match="无法读取题库文件"):
        parse_question_bank(tmp_path)


def test_split_questions_keeps_short_continuation():
    assert _split_questions("Do you like it? Why?") == ("Do you like it? Why?",)


def test_split_questions_splits_joined():
    assert _split_questions(
        "Do you like tea? Do you prefer coffee over tea?"
    ) == ("Do you like tea?", "Do you prefer coffee over tea?")


def test_all_layout_files_exist():
    for (region, kind), _ in SECTION_SOURCES:
        for filename, _, _ in FILE_LAYOUT:
            assert (BANK / region / kind / filename).is_file(), f"{region}/{kind}/{filename}"
