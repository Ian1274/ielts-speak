"""Auth endpoints: login / logout / me. No public registration."""
import re

from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel

from auth import create_session, delete_session, get_current_user, verify_password
from db import connect

router = APIRouter()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
MIN_PASSWORD_LEN = 6
COOKIE_NAME = "ielts_session"
COOKIE_MAX_AGE = 30 * 24 * 3600


class Credentials(BaseModel):
    username: str
    password: str


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=COOKIE_MAX_AGE, path="/",
    )


@router.post("/api/auth/login")
def login(creds: Credentials, response: Response) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, pass_hash, role FROM users WHERE username = ?",
            (creds.username,),
        ).fetchone()
        if row is None or not verify_password(creds.password, row["pass_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误。")
        token = create_session(conn, row["id"])
        role = row["role"]
    finally:
        conn.close()
    _set_cookie(response, token)
    return {"username": creds.username, "role": role}


@router.post("/api/auth/logout")
def logout(response: Response, token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    if token:
        conn = connect()
        try:
            delete_session(conn, token)
        finally:
            conn.close()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    conn = connect()
    try:
        user = get_current_user(conn, token)
    finally:
        conn.close()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录。")
    return {"username": user["username"], "role": user["role"]}
