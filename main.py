"""IELTS speaking random quiz — FastAPI app.

Serves the static frontend plus the parsed question bank at /api/data.
"""
import os
from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ielts.admin_api import router as admin_router
from ielts.auth import ensure_admin, require_user
from ielts.db import connect, init_db
from ielts.mock_api import create_mock_router
from ielts.session_api import create_session_router
from ielts.users_api import COOKIE_NAME, router as users_router
from ielts.parser import ParserError, build_payload, parse_question_bank
from ielts import tts

# 入口留在根目录:BASE_DIR 即项目根,question_bank/ 与 static/ 在此
BASE_DIR = Path(__file__).resolve().parent
BANK_DIR = Path(
    os.environ.get("IELTS_SPEAK_DATA", str(BASE_DIR / "question_bank"))
)


def create_app() -> FastAPI:
    # Parse once at startup; structural errors fail fast so systemd logs them.
    try:
        payload = build_payload(parse_question_bank(BANK_DIR))
    except ParserError as exc:
        raise SystemExit(f"题库解析失败: {exc}") from exc

    init_db()
    conn = connect()
    try:
        ensure_admin(conn)
    finally:
        conn.close()

    app = FastAPI(title="IELTS Speaking Quiz", docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.include_router(users_router)
    app.include_router(create_session_router(payload))
    app.include_router(create_mock_router(payload))
    app.include_router(admin_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/data")
    def api_data(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> JSONResponse:
        conn = connect()
        try:
            require_user(conn, token)
        finally:
            conn.close()
        try:
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except Exception as exc:  # defensive: never leak raw failures
            raise HTTPException(status_code=500, detail=f"题库解析失败: {exc}") from exc

    @app.get("/api/voices")
    def api_voices(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> JSONResponse:
        conn = connect()
        try:
            require_user(conn, token)
        finally:
            conn.close()
        return JSONResponse(
            {"voices": [{"id": v, "label": label} for v, label in tts.VOICES.items()]}
        )

    @app.get("/api/tts")
    def api_tts(
        text: str = Query(..., min_length=1),
        voice: str = Query(tts.DEFAULT_VOICE),
        rate: float = Query(tts.DEFAULT_RATE, ge=tts.MIN_RATE, le=tts.MAX_RATE),
        token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> Response:
        conn = connect()
        try:
            require_user(conn, token)
        finally:
            conn.close()
        error = tts.validate(voice, text, rate)
        if error:
            raise HTTPException(status_code=422, detail=error)
        try:
            audio = tts.synthesize(voice, text, rate)
        except tts.TtsError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(
            audio,
            media_type="audio/wav",
            headers={"Cache-Control": "public, max-age=604800"},
        )

    app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True))
    return app


app = create_app()
