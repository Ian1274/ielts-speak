"""POST /api/feedback + GET /api/feedback — ASR transcript + IELTS-style feedback.

Clients upload one answer clip (base64, ≤10MB) with the question context;
we transcribe it, compute stats, score it against the IELTS descriptors,
and persist the result. Transcription/scoring failures surface as 502 so
the client can show a friendly retry message without blocking practice.
"""
import json

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from ielts import asr, feedback
from ielts.auth import require_user
from ielts.db import connect
from ielts.users_api import COOKIE_NAME

PARTS = ("P1", "P2", "P3")
MODES = ("practice", "mock")
MAX_QUESTION_LEN = 500
MAX_DURATION = 600  # seconds; 10min per clip is far above any IELTS answer
MAX_B64_LEN = 14 * 1024 * 1024  # base64 of a 10MB clip


class FeedbackRequest(BaseModel):
    audio_b64: str
    mime: str
    duration_sec: float
    part: str
    question_text: str
    mode: str = "practice"


class FeedbackRouter:
    def __init__(self) -> None:
        self.router = APIRouter()
        self._register()

    def _register(self) -> None:
        r = self.router

        @r.post("/api/feedback")
        def api_feedback(
            body: FeedbackRequest,
            token: str | None = Cookie(default=None, alias=COOKIE_NAME),
        ) -> dict:
            # 系统边界验证:不信任外部数据
            if body.part not in PARTS:
                raise HTTPException(status_code=422, detail="题目类型无效。")
            if body.mode not in MODES:
                raise HTTPException(status_code=422, detail="模式无效。")
            if not body.question_text or len(body.question_text) > MAX_QUESTION_LEN:
                raise HTTPException(status_code=422, detail="题目文本无效。")
            if not 0 < body.duration_sec <= MAX_DURATION:
                raise HTTPException(status_code=422, detail="作答时长无效。")
            if not body.audio_b64 or len(body.audio_b64) > MAX_B64_LEN:
                raise HTTPException(status_code=422, detail="录音数据无效。")
            if (err := asr.validate_audio(body.audio_b64, body.mime)) is not None:
                raise HTTPException(status_code=422, detail=err)

            conn = connect()
            try:
                user = require_user(conn, token)
                try:
                    transcript = asr.transcribe(body.audio_b64, body.mime)
                except asr.AsrError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                try:
                    result = feedback.score(
                        transcript, body.question_text, body.part, body.duration_sec
                    )
                except feedback.FeedbackError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                stats = feedback.stats(transcript, body.duration_sec)
                scores = dict(result["scores"])
                pron_reason = None
                pron_error = None
                try:
                    pron = feedback.pronunciation_score(body.audio_b64, body.mime)
                    scores["pronunciation"] = pron["score"]
                    pron_reason = pron["reason"]
                except feedback.FeedbackError as exc:
                    # 发音降级:前三项已得,不整单失败
                    pron_error = str(exc)
                row = {
                    "transcript": transcript,
                    "stats": stats,
                    "scores": scores,
                    "summary": result["summary"],
                    "issues": result["issues"],
                    "advice": result["advice"],
                    "model_answer": result["model_answer"],
                    "pron_reason": pron_reason,
                    "pron_error": pron_error,
                }
                conn.execute(
                    """
                    INSERT INTO feedback
                      (user_id, mode, part, question_text, transcript,
                       duration_sec, scores_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["id"], body.mode, body.part, body.question_text,
                        transcript, body.duration_sec,
                        json.dumps(row, ensure_ascii=False),
                    ),
                )
                conn.commit()
                return row
            finally:
                conn.close()

        @r.get("/api/feedback")
        def api_feedback_list(
            token: str | None = Cookie(default=None, alias=COOKIE_NAME),
        ) -> dict:
            conn = connect()
            try:
                user = require_user(conn, token)
                rows = conn.execute(
                    """
                    SELECT id, mode, part, question_text, transcript,
                           duration_sec, scores_json, created_at
                    FROM feedback WHERE user_id = ?
                    ORDER BY id DESC LIMIT 20
                    """,
                    (user["id"],),
                ).fetchall()
                items = []
                for row in rows:
                    item = json.loads(row["scores_json"])
                    item.update(
                        {
                            "id": row["id"],
                            "part": row["part"],
                            "question_text": row["question_text"],
                            "created_at": row["created_at"],
                        }
                    )
                    items.append(item)
                return {"items": items}
            finally:
                conn.close()


def create_feedback_router() -> APIRouter:
    return FeedbackRouter().router
