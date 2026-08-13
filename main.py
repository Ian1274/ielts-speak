"""IELTS speaking random quiz — FastAPI app.

Serves the static frontend plus the parsed question bank at /api/data.
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from auth import ensure_admin
from db import connect, init_db
from users_api import router as users_router
from parser import ParserError, build_payload, parse_speak_md
import tts

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = Path(
    os.environ.get("IELTS_SPEAK_DATA", str(BASE_DIR / "2605-08-speak.md"))
)


def create_app() -> FastAPI:
    # Parse once at startup; structural errors fail fast so systemd logs them.
    try:
        payload = build_payload(parse_speak_md(DATA_FILE))
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

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/data")
    def api_data() -> JSONResponse:
        try:
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})
        except Exception as exc:  # defensive: never leak raw failures
            raise HTTPException(status_code=500, detail=f"题库解析失败: {exc}") from exc

    @app.get("/api/voices")
    def api_voices() -> JSONResponse:
        return JSONResponse(
            {"voices": [{"id": v, "label": label} for v, label in tts.VOICES.items()]}
        )

    @app.get("/api/tts")
    def api_tts(
        text: str = Query(..., min_length=1),
        voice: str = Query(tts.DEFAULT_VOICE),
        rate: float = Query(tts.DEFAULT_RATE, ge=tts.MIN_RATE, le=tts.MAX_RATE),
    ) -> Response:
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
