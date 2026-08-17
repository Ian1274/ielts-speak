"""POST /api/mock/session + /api/mock/finish — full mock speaking exam.

The whole exam packet is drawn once at session creation, with the same 7-day
avoidance weighting as practice mode (history is shared across modes). History
rows are written only at finish, for the questions the candidate actually
answered — skipped or abandoned questions leave no trace. The Nth-test
greeting counts completed mock sessions only.
"""
import json
import random
from collections import Counter

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

import mock_fixed
import tts
from auth import require_user
from db import connect
from sampling import item_key, sample_questions_from_topic, sample_session, sample_topics
from users_api import COOKIE_NAME

FIRST_TOPICS = (mock_fixed.P1_TOPIC_A, mock_fixed.P1_TOPIC_B)
P1_TOPIC_COUNT = 2
P2_FOLLOWUP_COUNT = 3
MAX_DURATION = 3600  # seconds; upper bound for client-reported stage timings


class SessionRequest(BaseModel):
    section: str
    voice: str


class FinishRequest(BaseModel):
    session_id: int
    answered_keys: list[str] = []
    durations: dict[str, float] = {}
    abandoned: bool = False


def _recent_counter(conn, user_id: int) -> Counter[str]:
    rows = conn.execute(
        """
        SELECT item_key, COUNT(*) AS c FROM history
        WHERE user_id = ? AND drawn_at >= datetime('now', '-7 days')
        GROUP BY item_key
        """,
        (user_id,),
    ).fetchall()
    return Counter({r["item_key"]: r["c"] for r in rows})


def _completed_count(conn, user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM mock_sessions WHERE user_id = ? AND status = 'completed'",
        (user_id,),
    ).fetchone()
    return row["n"]


def _draw_packet(payload: dict, section: str, recent: Counter, rng: random.Random) -> dict:
    """Draw the full exam packet; every question carries a history item_key."""
    # P1 第一主题:固定首问 + 备选抽 2
    first = rng.choice(FIRST_TOPICS)
    backups = rng.sample(first["backup"], 2)
    first_questions = [
        {"text": text, "key": item_key(section, "P1", first["topic"], text)}
        for text in (first["lead"],) + tuple(backups)
    ]

    # P1 第二、三主题:随机 2 主题 × 每主题 2–3 问(主题不重复)
    p1_topics = []
    for t in sample_topics(payload, section, "P1", P1_TOPIC_COUNT, recent, rng):
        count = rng.choice((2, 3))
        texts, keys = sample_questions_from_topic(t, section, "P1", count, recent, rng)
        p1_topics.append(
            {
                "topic": t["topic"],
                "questions": [
                    {"text": text, "key": key} for text, key in zip(texts, keys)
                ],
            }
        )

    # P2:题卡 1 张(参与 7 天避重,与练习模式共用历史)
    items, _with_replacement, keys = sample_session(payload, section, "P2", 1, recent, rng)
    p2 = items[0]
    p2_key = keys[0]

    # P3:与 P2 同主题抽 3 问;题库漂移时防御性回退到首个 P3 主题
    p3_topic = next(
        (t for t in payload["sections"][section]["P3"] if t["topic"] == p2["topic"]),
        payload["sections"][section]["P3"][0],
    )
    p3_texts, p3_keys = sample_questions_from_topic(
        p3_topic, section, "P3", P2_FOLLOWUP_COUNT, recent, rng
    )

    return {
        "p1First": {"topic": first["topic"], "questions": first_questions},
        "p1Topics": p1_topics,
        "p2": {"topic": p2["topic"], "card": list(p2["card"]), "key": p2_key},
        "p3": {
            "topic": p3_topic["topic"],
            "questions": [
                {"text": text, "key": key} for text, key in zip(p3_texts, p3_keys)
            ],
        },
    }


def _packet_entries(packet: dict, section: str) -> list[dict]:
    """Flatten the packet into history entries (part, topic, item_key, text)."""
    entries = []
    for q in packet["p1First"]["questions"]:
        entries.append(
            {"section": section, "part": "P1",
             "topic": packet["p1First"]["topic"],
             "item_key": q["key"], "text": q["text"]}
        )
    for t in packet["p1Topics"]:
        for q in t["questions"]:
            entries.append(
                {"section": section, "part": "P1", "topic": t["topic"],
                 "item_key": q["key"], "text": q["text"]}
            )
    entries.append(
        {"section": section, "part": "P2", "topic": packet["p2"]["topic"],
         "item_key": packet["p2"]["key"], "text": "\n".join(packet["p2"]["card"])}
    )
    for q in packet["p3"]["questions"]:
        entries.append(
            {"section": section, "part": "P3", "topic": packet["p3"]["topic"],
             "item_key": q["key"], "text": q["text"]}
        )
    return entries


def _build_scripts(packet: dict, nth: int) -> dict:
    return {
        "opening": mock_fixed.OPENING.format(
            greeting=mock_fixed.greeting(), examiner=mock_fixed.EXAMINER_NAME, n=nth
        ),
        "idCheck": mock_fixed.ID_CHECK,
        "p2Transition": mock_fixed.P2_TRANSITION,
        "p2PrepEnd": mock_fixed.P2_PREP_END,
        "p3Transition": mock_fixed.P3_TRANSITION.format(topic=packet["p2"]["topic"]),
        "closing": mock_fixed.CLOSING,
    }


def create_mock_router(payload: dict) -> APIRouter:
    router = APIRouter()

    @router.post("/api/mock/session")
    def api_mock_session(
        body: SessionRequest,
        token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        # 系统边界验证:不信任外部数据
        if body.section not in payload.get("sections", {}):
            raise HTTPException(status_code=422, detail="题库数据缺失,请刷新页面重试。")
        if body.voice not in tts.VOICES and body.voice not in tts.VOICE_ALIASES:
            raise HTTPException(status_code=422, detail="未知发音人。")

        conn = connect()
        try:
            user = require_user(conn, token)
            recent = _recent_counter(conn, user["id"])
            nth = _completed_count(conn, user["id"]) + 1
            rng = random.Random()
            packet = _draw_packet(payload, body.section, recent, rng)
            scripts = _build_scripts(packet, nth)
            entries = _packet_entries(packet, body.section)
            cur = conn.execute(
                "INSERT INTO mock_sessions (user_id, section, voice, drawn_json) "
                "VALUES (?, ?, ?, ?)",
                (user["id"], body.section, body.voice,
                 json.dumps({"entries": entries}, ensure_ascii=False)),
            )
            conn.commit()
            session_id = cur.lastrowid
            return {
                "sessionId": session_id,
                "nth": nth,
                "scripts": scripts,
                "packet": packet,
            }
        finally:
            conn.close()

    @router.post("/api/mock/finish")
    def api_mock_finish(
        body: FinishRequest,
        token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> dict:
        if any(
            not isinstance(v, (int, float)) or not 0 <= v <= MAX_DURATION
            for v in body.durations.values()
        ):
            raise HTTPException(status_code=422, detail="环节时长数据无效。")

        conn = connect()
        try:
            user = require_user(conn, token)
            row = conn.execute(
                "SELECT * FROM mock_sessions WHERE id = ? AND user_id = ?",
                (body.session_id, user["id"]),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="本场模拟不存在。")
            if row["status"] != "created":
                return {"ok": True, "already": True}

            if body.abandoned:
                conn.execute(
                    "UPDATE mock_sessions SET status = 'abandoned' WHERE id = ?",
                    (body.session_id,),
                )
                conn.commit()
                return {"ok": True, "abandoned": True}

            drawn = json.loads(row["drawn_json"] or "{}").get("entries", [])
            by_key = {e["item_key"]: e for e in drawn}
            rows = [
                (user["id"], e["section"], e["part"], e["topic"],
                 e["item_key"], "mock", body.session_id)
                for k in body.answered_keys
                if (e := by_key.get(k)) is not None
            ]
            conn.executemany(
                """
                INSERT INTO history (user_id, section, part, topic, item_key, mode, mock_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.execute(
                "UPDATE mock_sessions SET status = 'completed', completed_at = "
                "datetime('now'), durations_json = ? WHERE id = ?",
                (json.dumps(body.durations, ensure_ascii=False), body.session_id),
            )
            conn.commit()
            return {"ok": True, "recorded": len(rows)}
        finally:
            conn.close()

    return router
