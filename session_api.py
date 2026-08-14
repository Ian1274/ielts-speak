"""POST /api/session — server-side weighted sampling + history recording.

强制登录:每位用户按 7 天内抽题历史避重加权,并记录本轮抽题。
"""
import random
from collections import Counter

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import require_user
from db import connect
from sampling import sample_session
from users_api import COOKIE_NAME

PART_ORDER = ("P1", "P2", "P3")


class SessionRequest(BaseModel):
    section: str
    part: str
    count: int


def create_session_router(payload: dict) -> APIRouter:
    router = APIRouter()

    @router.post("/api/session")
    def api_session(
        body: SessionRequest, token: str | None = Cookie(default=None, alias=COOKIE_NAME)
    ) -> dict:
        # 系统边界验证:不信任外部数据(文案与前端 validateConfig 一致)
        if body.section not in payload.get("sections", {}):
            raise HTTPException(status_code=422, detail="题库数据缺失,请刷新页面重试。")
        if body.part not in PART_ORDER:
            raise HTTPException(status_code=422, detail="题型无效。")
        if not isinstance(body.count, int) or not 1 <= body.count <= 10:
            raise HTTPException(status_code=422, detail="题目数量需为 1–10 的整数。")
        topics = payload["sections"][body.section][body.part]
        usable = [
            t for t in topics
            if (t["card"] if body.part == "P2" else t["questions"])
        ]
        if not usable:
            raise HTTPException(status_code=422, detail="该类别暂无可用题目。")

        conn = connect()
        try:
            user = require_user(conn, token)
            rows = conn.execute(
                """
                SELECT item_key, COUNT(*) AS c FROM history
                WHERE user_id = ? AND drawn_at >= datetime('now', '-7 days')
                GROUP BY item_key
                """,
                (user["id"],),
            ).fetchall()
            recent = Counter({r["item_key"]: r["c"] for r in rows})

            rng = random.Random()
            items, with_replacement, keys = sample_session(
                payload, body.section, body.part, body.count, recent, rng
            )

            if keys:
                rows = [
                    (user["id"], body.section, body.part, it["topic"], k)
                    for k, it in zip(keys, items)
                ]
                conn.executemany(
                    """
                    INSERT INTO history (user_id, section, part, topic, item_key)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
        finally:
            conn.close()
        return {"items": list(items), "withReplacement": with_replacement}

    return router
