"""Admin endpoints: user management and practice stats (admin role only)."""
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import hash_password, require_admin
from db import connect
from users_api import COOKIE_NAME, MIN_PASSWORD_LEN, USERNAME_RE

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class PasswordReset(BaseModel):
    password: str


@router.get("/api/admin/users")
def list_users(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    conn = connect()
    try:
        require_admin(conn, token)
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.created_at,
                   COUNT(h.id) AS draws_total,
                   COALESCE(SUM(CASE WHEN h.drawn_at >= datetime('now', '-7 days')
                                     THEN 1 ELSE 0 END), 0) AS draws_7d
            FROM users u LEFT JOIN history h ON h.user_id = u.id
            GROUP BY u.id ORDER BY u.id
            """
        ).fetchall()
    finally:
        conn.close()
    return {"users": [dict(r) for r in rows]}


@router.post("/api/admin/users")
def create_user(body: UserCreate, token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    if not USERNAME_RE.fullmatch(body.username):
        raise HTTPException(status_code=422, detail="用户名需为 2–32 位字母、数字、下划线或连字符。")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"密码至少 {MIN_PASSWORD_LEN} 位。")
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="角色无效。")
    conn = connect()
    try:
        require_admin(conn, token)
        if conn.execute(
            "SELECT id FROM users WHERE username = ?", (body.username,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="用户名已存在。")
        conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES (?, ?, ?)",
            (body.username, hash_password(body.password), body.role),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.delete("/api/admin/users/{user_id}")
def delete_user(user_id: int, token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    conn = connect()
    try:
        admin = require_admin(conn, token)
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="不能删除当前登录的管理员。")
        if conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="用户不存在。")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/password")
def reset_password(
    user_id: int,
    body: PasswordReset,
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=422, detail=f"密码至少 {MIN_PASSWORD_LEN} 位。")
    conn = connect()
    try:
        require_admin(conn, token)
        if conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="用户不存在。")
        conn.execute(
            "UPDATE users SET pass_hash = ? WHERE id = ?",
            (hash_password(body.password), user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
