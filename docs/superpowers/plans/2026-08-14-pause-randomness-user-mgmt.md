# 暂停键 + 随机性优化 + 用户管理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为雅思口语随机练习增加暂停键、服务端避重加权抽样、用户体系(关闭公开注册,管理员后台建号,管理员由环境变量注入)。

**Architecture:** 三个子系统:①暂停 = 纯前端状态机改造(冻结 deadline、中断音频、恢复重读);②加权抽样 = 抽样逻辑从浏览器搬到服务端 `/api/session`,按用户 7 天内抽题历史做衰减加权(`0.25^次数`),未登录退化为均匀抽样;③用户管理 = SQLite(标准库 sqlite3)存 users/sessions/history,PBKDF2 密码哈希 + HttpOnly Cookie 会话。公开注册关闭,普通账号只能由管理员在 `/admin.html` 创建;管理员账号由 `IELTS_ADMIN_USER`/`IELTS_ADMIN_PASSWORD` 环境变量注入,启动时确保存在(缺则建、同名存在则同步密码并提权)。

**Tech Stack:** Python 3.12 · FastAPI + uvicorn · 标准库 sqlite3/hashlib/hmac/secrets · 原生 JS ES modules · pytest + httpx (仅开发)

**Spec:** 本文档「需求」节(与用户 2026-08-14 对话确认:用户管理=管理后台+账号体系、注册关闭仅后台建号、管理员=ian1274(密码存 .env 不进仓库)、随机=避重加权抽样、暂停=暂停计时+中断语音)。

## 需求

1. **暂停键**:练习中途按暂停 → 倒计时冻结、正在播放的 TTS 中断;按继续 → 剩余时间继续倒计时;若语音被中断(题没读完)则恢复时重读当前题,然后才开始倒计时。
2. **随机性**:有人反馈重复太多。当前 `Math.random()` 无偏差但会话间零记忆。方案:服务端记录每人抽题历史,近 7 天出现过的题降权(每次出现权重 ×0.25),全部题都被抽过时回退均匀抽样。会话内严格不重复。未登录用户仍可用(均匀抽样,不记历史)。
3. **用户管理**:关闭公开注册(无注册端点);密码登录 + 会话;管理员后台(用户列表/建号/删号/重置密码/练习统计);管理员由环境变量注入,账号 `ian1274`,密码 `Yyx991274` 只写 .env 与 VPS 环境,不进仓库、不进 README。

## Global Constraints

- 包管理:`uv`;运行 `uv run python ...`;安装 `uv add ...`。Python 版本以 `.python-version`(3.12)为准。
- 不可变性:创建新对象,不修改现有对象。
- 文件组织:多个小文件优于少数大文件(200-400 行,最多 800 行)。
- 错误处理:每层显式处理,快速失败,不静默吞错。系统边界验证所有输入,不信任外部数据。
- 前端无构建工具,原生 ES modules;后端零新增运行时依赖(只用标准库 sqlite3 等)。
- 抽题 API 保持与现有前端数据形状兼容:`{topic, pairedTopic, pairedPart, text}`(P1/P3)、`{topic, card}`(P2)。
- 未登录必须可用(公开部署的兜底),登录为增强项。
- 无 `/api/auth/register` 端点;管理员凭据只存环境变量(.env,gitignored)。

---

## File Structure

```
ielts_speak/
├── db.py                  # 新增:SQLite 连接、schema、init_db
├── auth.py                # 新增:密码哈希、会话 token、ensure_admin、require_user/require_admin
├── users_api.py           # 新增:登录/登出/me 路由(无注册)
├── admin_api.py           # 新增:管理路由(用户 CRUD + 统计)
├── session_api.py         # 新增:POST /api/session 加权抽样 + 历史落库
├── sampling.py            # 新增:纯抽样逻辑(可测、无 IO)
├── main.py                # 修改:init_db、ensure_admin 接线、挂载三个路由
├── static/
│   ├── speech.js          # 修改:cancel() 结算 pending promise
│   ├── app.js             # 修改:暂停状态机、接 /api/session、登录 UI
│   ├── auth.js            # 新增:登录/登出/me 的 UI 与 API 封装
│   ├── admin.html         # 新增:管理后台页
│   ├── admin.js           # 新增:管理后台逻辑
│   ├── admin.css          # 新增:管理后台样式
│   ├── index.html         # 修改:暂停按钮、登录区(仅登录,无注册)
│   └── style.css          # 修改:authbar/authform/input 样式
├── tests/
│   ├── conftest.py        # 新增:隔离 DB + 注入管理员 env 的 fixture
│   ├── test_db.py         # 新增
│   ├── test_auth.py       # 新增
│   ├── test_users_api.py  # 新增
│   ├── test_sampling.py   # 新增
│   ├── test_session_api.py# 新增
│   └── test_admin_api.py  # 新增
├── .env.example           # 修改:IELTS_ADMIN_USER/PASSWORD、IELTS_DB
├── .gitignore             # 修改:加 ielts.db
└── README.md              # 修改:新功能、账号说明(不含真实密码)、部署
```

依赖关系:Phase A(暂停)独立 → Phase B(DB+认证) → Phase C(抽样,依赖 B) → Phase D(管理后台,依赖 B/C) → Phase E(前端整合,依赖 C) → Phase F(文档+部署)。

---

## Phase A:暂停键

### Task A1:speech.js — cancel() 结算挂起的播放 Promise

**背景:** 当前 `cancel()` 只 `pause()` 音频,`speakTts` 的 Promise 永不被 settle → `runSequence` 卡在 `await speakQuestion`。暂停/停止都依赖 cancel 让 await 返回。

**Files:**
- Modify: `static/speech.js`

**Interfaces:**
- Produces: `export class CancelledError extends Error`;`export function cancel()` 行为改为:停音频 + 用 `CancelledError` reject 当前挂起的播放 Promise(若无挂起则 no-op)。

- [ ] **Step 1: 加模块级 pendingReject 与 CancelledError**

`static/speech.js` 顶部(audioEl 声明后)加:

```js
let pendingReject = null;

// cancel() 时用于中断正在等待的播放 Promise,区别于播放失败。
export class CancelledError extends Error {
  constructor() {
    super("已取消");
    this.name = "CancelledError";
  }
}
```

- [ ] **Step 2: speakTts 播放 Promise 登记 reject**

把 `speakTts` 内 `audioEl.onended/onerror/play()` 那段替换为:

```js
      return new Promise((resolve, reject) => {
        pendingReject = reject;
        audioEl.onended = () => { pendingReject = null; resolve(); };
        audioEl.onerror = () => { pendingReject = null; reject(new Error("音频播放失败")); };
        audioEl.play().catch(() => { pendingReject = null; reject(new Error("音频播放失败")); });
      });
```

- [ ] **Step 3: startUtterance 登记 reject**

`startUtterance` 内改为:

```js
  pendingReject = reject;
  u.onend = () => { pendingReject = null; resolve(); };
  u.onerror = () => { pendingReject = null; reject(new Error("语音播报中断。")); };
```

- [ ] **Step 4: cancel() 结算 pending promise**

`cancel()` 末尾追加:

```js
  if (pendingReject) {
    const reject = pendingReject;
    pendingReject = null;
    reject(new CancelledError());
  }
```

- [ ] **Step 5: 浏览器冒烟验证**

`uv run uvicorn main:app --port 8000` → Playwright 打开 `http://127.0.0.1:8000`,开始 P1 一题,音频播放中按「停止」,确认页面回到设置页、控制台无未处理 Promise 报错。

- [ ] **Step 6: Commit**

```bash
git add static/speech.js
git commit -m "fix: cancel() settles pending playback promise with CancelledError"
```

---

### Task A2:app.js — 暂停/继续状态机 + 按钮

**Files:**
- Modify: `static/app.js`(session 对象、runSequence、countdown、startSession、finishSession、showConfig、stop 处理器、replay 处理器、新增 waitResume 与 pause 处理器)
- Modify: `static/index.html`(session actions 行加暂停按钮)

**Interfaces:**
- Consumes: `CancelledError` from `./speech.js`
- Produces: `session.paused/phase/deadline/pauseStart` 字段;`#pause` 按钮(id 固定);行为契约:P1/P3 语音中被暂停 → 恢复后重读;倒计时中被暂停 → 恢复后从剩余时间继续;P2 无语音只有倒计时冻结。

- [ ] **Step 1: index.html 加暂停按钮**

`static/index.html` 的 `session__actions` 内,`#replay` 之后插入:

```html
<button class="btn btn--ghost" id="pause" hidden>暂停</button>
```

- [ ] **Step 2: session 状态对象加字段**

`static/app.js` 的 `session` 对象追加:

```js
  paused: false,      // 暂停中
  phase: null,        // "audio" | "countdown" | null — 当前题所处阶段
  deadline: null,     // 倒计时绝对截止时间戳(ms)
  pauseStart: null,   // 本次暂停起始时间戳(ms)
```

- [ ] **Step 3: els 注册 pause 按钮**

`els` 对象加 `pause: $("pause"),`。

- [ ] **Step 4: 暂停/继续点击处理器**

在 `els.replay` 处理器之后加:

```js
els.pause.addEventListener("click", () => {
  if (session.state !== "running") return;
  if (session.paused) {
    // 恢复：倒计时阶段把 deadline 顺延暂停时长；语音阶段由 runSequence 重读
    if (session.phase === "countdown" && session.pauseStart !== null) {
      session.deadline += Date.now() - session.pauseStart;
    }
    session.paused = false;
    els.pause.textContent = "暂停";
    els.pause.setAttribute("aria-pressed", "false");
  } else {
    session.paused = true;
    session.pauseStart = Date.now();
    cancel();
    els.pause.textContent = "继续";
    els.pause.setAttribute("aria-pressed", "true");
  }
});
```

- [ ] **Step 5: runSequence 支持语音中断重读**

替换现有 `runSequence` 为:

```js
async function runSequence() {
  if (session.part !== "P2") {
    if (!session.voice && isSupported()) session.voice = await ensureVoices();
  }

  for (const item of session.items) {
    if (session.cancelled) break;
    renderItem(item);
    session.phase = "audio";
    if (session.part !== "P2") {
      await speakQuestion(item.text);
      if (session.cancelled) break;
      if (session.paused) {           // 语音中被暂停：恢复后重读一遍
        await waitResume();
        if (session.cancelled) break;
        await speakQuestion(item.text);
        if (session.cancelled) break;
      }
    }
    session.phase = "countdown";
    await countdown();
    session.phase = null;
    if (session.cancelled) break;
  }
  if (!session.cancelled) finishSession();
}
```

- [ ] **Step 6: countdown 支持冻结 + 取消提前退出**

替换现有 `countdown` 为:

```js
function countdown() {
  return new Promise((resolve) => {
    session.deadline = Date.now() + session.pauseMs;
    session.pauseStart = null;
    const startSec = session.pauseMs / 1000;
    const tick = () => {
      if (session.cancelled) { stopTimer(); resolve(); return; }
      if (session.paused) return; // 冻结：不更新显示、不推进计时
      const remain = Math.max(0, Math.ceil((session.deadline - Date.now()) / 1000));
      els.clock.textContent = String(remain);
      els.hand.setAttribute("transform", `rotate(${(1 - remain / startSec) * 360} 100 100)`);
      els.clock.classList.toggle("clock--urgent", remain <= 10 && remain > 0);
      els.dial.classList.toggle("dial--urgent", remain <= 10 && remain > 0);
      if (remain <= 0) {
        stopTimer();
        resolve();
      }
    };
    tick();
    session.timerId = setInterval(tick, 200);
  });
}
```

并在其后新增:

```js
// 暂停屏障：runSequence 在语音被暂停中断后等待用户按「继续」。
function waitResume() {
  return new Promise((resolve) => {
    const iv = setInterval(() => {
      if (!session.paused || session.cancelled) {
        clearInterval(iv);
        resolve();
      }
    }, 150);
  });
}
```

- [ ] **Step 7: speakQuestion 取消时不降级到浏览器 TTS**

`speakQuestion` 的 catch 开头加:

```js
  } catch (err) {
    if (err instanceof CancelledError || session.cancelled || session.paused) return;
```

顶部 import 改:`import { speakTts, speakBrowser, ensureVoices, isSupported, cancel, CancelledError } from "./speech.js";`

- [ ] **Step 8: replay 仅在倒计时阶段可用**

替换 replay 处理器守卫:

```js
els.replay.addEventListener("click", () => {
  if (session.state !== "running" || session.paused || session.phase !== "countdown" || session.part === "P2") return;
```

(倒计时阶段无在途播放 Promise,`cancel()` no-op,不会触发降级或双播。)

- [ ] **Step 9: 生命周期复位**

- `startSession` 内(`session.topicVisible = false;` 之后)加:`session.paused = false;` 和 `els.pause.hidden = false;`
- `finishSession` 内(`els.replay.hidden = true;` 之后)加:`els.pause.hidden = true;`
- `showConfig` 内(`session.state = "idle";` 之后)加:

```js
  session.paused = false;
  els.pause.hidden = true;
  els.pause.textContent = "暂停";
  els.pause.setAttribute("aria-pressed", "false");
```

- [ ] **Step 10: Commit**

```bash
git add static/app.js static/index.html
git commit -m "feat: pause/resume mid-session with frozen countdown and audio restart"
```

---

### Task A3:Playwright 手工验证暂停行为

**Files:** 无代码改动。

- [ ] **Step 1: 启动本地服务**

`uv run uvicorn main:app --port 8000`(后台运行)。

- [ ] **Step 2: 验证 6 个场景**(Playwright MCP 打开 `http://127.0.0.1:8000`)

1. P1 1 题开始 → TTS 播放中按「暂停」→ 音频立即停,按钮变「继续」,时钟显示满格 → 按「继续」→ 完整重读该题 → 倒计时从满格开始走。
2. 倒计时走到 ~90 时按「暂停」→ 时钟冻结在 90,指针冻结 → 等 10 秒仍 90 → 按「继续」→ 从 90 继续走。
3. P2 1 题开始 → 倒计时中暂停 → 冻结 → 继续 → 顺延走完 → 进入完成页。
4. 最后 10 秒(红色 urgent 态)暂停 → urgent 态保持 → 继续 → 归零进下一题/完成页。
5. 暂停状态下按「停止」→ 回设置页,无卡死、无残留定时器(再开始一轮正常)。
6. 倒计时中按「🔊 重听」→ 重读该题,时钟继续走;语音播放中按重听 → 无反应(守卫生效)。

- [ ] **Step 3: 关闭本地服务**

- [ ] **Step 4: Commit(如有修复)**

```bash
git add static/
git commit -m "test: manual verification of pause/resume flows"
```

---

## Phase B:数据层与认证

### Task B1:测试基建 + db.py

**Files:**
- Modify: `pyproject.toml`(dev 依赖)
- Create: `db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`
- Modify: `main.py`(create_app 中调用 init_db)

**Interfaces:**
- Produces: `db.get_db_path() -> Path`(每次调用读环境变量 `IELTS_DB`,默认 `项目根/ielts.db`)、`db.connect() -> sqlite3.Connection`(row_factory=Row,外键开)、`db.init_db() -> None`(幂等建表)、`db.SCHEMA`(建表 SQL)。
- Consumes: 无。

- [ ] **Step 1: 加开发依赖**

Run: `uv add --dev pytest httpx`
Expected: pyproject 出现 `[dependency-groups] dev = ["pytest>=...", "httpx>=..."]`。

- [ ] **Step 2: 写失败测试 tests/test_db.py**

```python
import sqlite3

import pytest

import db


def test_init_db_creates_tables():
    db.init_db()
    conn = db.connect()
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    assert {"users", "sessions", "history"} <= names


def test_foreign_keys_enforced():
    db.init_db()
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) "
                "VALUES ('t', 999, '2030-01-01 00:00:00')"
            )
    finally:
        conn.close()


def test_history_cascades_on_user_delete():
    db.init_db()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES ('u1', 'x', 'user')"
        )
        conn.commit()
        uid = cur.lastrowid
        conn.execute(
            "INSERT INTO history (user_id, section, part, topic, item_key) "
            "VALUES (?, 'S', 'P1', 'T', 'k')",
            (uid,),
        )
        conn.commit()
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        left = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
    finally:
        conn.close()
    assert left == 0
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL(ModuleNotFoundError: No module named 'db')。

- [ ] **Step 4: 实现 db.py**

```python
"""SQLite storage for users, sessions, and practice history.

Connections are short-lived (opened per call). Schema is initialized once
at startup via init_db(). Path overridable via IELTS_DB env var.
"""
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "ielts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    pass_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    section TEXT NOT NULL,
    part TEXT NOT NULL,
    topic TEXT NOT NULL,
    item_key TEXT NOT NULL,
    drawn_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_history_user_time ON history(user_id, drawn_at);
"""


def get_db_path() -> Path:
    return Path(os.environ.get("IELTS_DB", str(DEFAULT_DB)))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: 3 PASS。

- [ ] **Step 6: conftest.py — 隔离 DB + 注入管理员 env 的 fixture**

```python
import os

import pytest

from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def test_env(tmp_path_factory):
    """Point IELTS_DB at a throwaway dir and seed admin env BEFORE main import."""
    os.environ.setdefault("IELTS_DB", str(tmp_path_factory.mktemp("dbs") / "default.db"))
    os.environ.setdefault("IELTS_ADMIN_USER", "admin")
    os.environ.setdefault("IELTS_ADMIN_PASSWORD", "secret123")
    import main  # noqa: F401  (module-level app=create_app() runs with test env)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh DB per test; admin seeded from env by create_app."""
    monkeypatch.setenv("IELTS_DB", str(tmp_path / "fresh.db"))
    monkeypatch.setenv("IELTS_ADMIN_USER", "admin")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "secret123")
    import db
    from main import create_app

    db.init_db()
    with TestClient(create_app()) as c:
        yield c
```

注意:`db.get_db_path()` 每次调用读环境变量,所以 fixture 级 monkeypatch 生效;`main` 在 session fixture 里先于任何测试导入,模块级 `app = create_app()` 不会碰真实 `ielts.db`。

- [ ] **Step 7: main.py 接线 init_db**

`create_app()` 内、`app = FastAPI(...)` 之前加 `init_db()`;顶部 import 加 `from db import init_db`。

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock db.py tests/conftest.py tests/test_db.py main.py
git commit -m "feat: sqlite storage layer with test harness"
```

---

### Task B2:auth.py — 密码哈希、会话 token、管理员注入

**Files:**
- Create: `auth.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Consumes: `db.connect()`
- Produces:
  - `hash_password(password: str) -> str`(格式 `pbkdf2$<salt hex>$<digest hex>`,PBKDF2-SHA256 200k 迭代)
  - `verify_password(password: str, stored: str) -> bool`(常量时间比较,畸形存储返回 False)
  - `create_session(conn, user_id: int) -> str`(插入 sessions 行,返回 token)
  - `delete_session(conn, token: str) -> None`
  - `get_current_user(conn, token: str | None) -> dict | None`(过期清理+查询,返回 `{id, username, role}`)
  - `ensure_admin(conn) -> None`(读 `IELTS_ADMIN_USER`/`IELTS_ADMIN_PASSWORD`;缺 env 则 no-op;账号不存在则建为 admin,存在则同步密码并提权 admin)
  - `require_user(conn, token) -> dict`(401 抛 HTTPException)
  - `require_admin(conn, token) -> dict`(403 抛 HTTPException)

- [ ] **Step 1: 写失败测试 tests/test_auth.py**

```python
import db


def _init():
    db.init_db()


def _make_user(username="alice", role="user", password="secret123"):
    import auth
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES (?, ?, ?)",
            (username, auth.hash_password(password), role),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_hash_verify_roundtrip():
    import auth
    stored = auth.hash_password("secret123")
    assert stored.startswith("pbkdf2$")
    assert auth.verify_password("secret123", stored) is True
    assert auth.verify_password("wrong", stored) is False


def test_verify_malformed_storage_returns_false():
    import auth
    assert auth.verify_password("x", "not-a-hash") is False
    assert auth.verify_password("x", "pbkdf2$zz$zz") is False


def test_hash_is_salted():
    import auth
    assert auth.hash_password("same") != auth.hash_password("same")


def test_session_roundtrip():
    import auth
    _init()
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        user = auth.get_current_user(conn, token)
        assert user is not None
        assert user["username"] == "alice"
        assert user["role"] == "user"
        auth.delete_session(conn, token)
        assert auth.get_current_user(conn, token) is None
    finally:
        conn.close()


def test_expired_session_rejected():
    import auth
    _init()
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        conn.execute(
            "UPDATE sessions SET expires_at = '2000-01-01 00:00:00' WHERE token = ?",
            (token,),
        )
        conn.commit()
        assert auth.get_current_user(conn, token) is None
        n = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        assert n == 0
    finally:
        conn.close()


def test_require_admin_forbids_user_role():
    import auth
    _init()
    uid = _make_user()
    conn = db.connect()
    try:
        token = auth.create_session(conn, uid)
        try:
            auth.require_admin(conn, token)
            assert False, "expected 403"
        except auth.HTTPException as exc:
            assert exc.status_code == 403
    finally:
        conn.close()


def test_require_user_rejects_missing_token():
    import auth
    _init()
    conn = db.connect()
    try:
        try:
            auth.require_user(conn, None)
            assert False, "expected 401"
        except auth.HTTPException as exc:
            assert exc.status_code == 401
    finally:
        conn.close()


def test_ensure_admin_creates_from_env(monkeypatch):
    import auth
    monkeypatch.setenv("IELTS_ADMIN_USER", "root")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "rootpass1")
    _init()
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        row = conn.execute("SELECT * FROM users WHERE username = 'root'").fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["role"] == "admin"
    assert auth.verify_password("rootpass1", row["pass_hash"])


def test_ensure_admin_upserts_existing_user(monkeypatch):
    import auth
    monkeypatch.setenv("IELTS_ADMIN_USER", "ian1274")
    monkeypatch.setenv("IELTS_ADMIN_PASSWORD", "newpass1")
    _init()
    uid = _make_user(username="ian1274", role="user", password="oldpass1")
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    finally:
        conn.close()
    assert row["role"] == "admin"
    assert auth.verify_password("newpass1", row["pass_hash"])
    assert not auth.verify_password("oldpass1", row["pass_hash"])


def test_ensure_admin_noop_without_env(monkeypatch):
    import auth
    monkeypatch.delenv("IELTS_ADMIN_USER", raising=False)
    monkeypatch.delenv("IELTS_ADMIN_PASSWORD", raising=False)
    _init()
    conn = db.connect()
    try:
        auth.ensure_admin(conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    finally:
        conn.close()
    assert n == 0
```

注:`auth.HTTPException` 需 auth.py 导出(见实现);各测试独立 `db.init_db()` 幂等,但**注意:测试共享同一 DB 文件时用户会互相污染**——test_auth 各测试用不同用户名/独立断言,不依赖「库为空」。若出现串扰,把 `_init` 换成 per-test tmp 路径(conftest 已有 client fixture 模式,test_auth 直接连接需自行 monkeypatch `IELTS_DB`)。实现时以跑通为准,必要时给 test_auth 加 `tmp_path` fixture 隔离。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL(no module named 'auth')。

- [ ] **Step 3: 实现 auth.py**

```python
"""Password hashing, session tokens, and admin bootstrap."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

PBKDF2_ITERATIONS = 200_000
SESSION_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(actual, expected)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + SESSION_TTL).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    conn.commit()
    return token


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def get_current_user(conn: sqlite3.Connection, token: str | None) -> dict | None:
    """Return {id, username, role} for a valid token, else None."""
    if not token:
        return None
    now = _now()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.commit()
    row = conn.execute(
        """
        SELECT u.id, u.username, u.role
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, now),
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def ensure_admin(conn: sqlite3.Connection) -> None:
    """Bootstrap admin account from env (IELTS_ADMIN_USER / IELTS_ADMIN_PASSWORD).

    Env is authoritative: a missing account is created as admin; an existing
    account with the same name is promoted to admin and its password reset
    to the env value. No-op when either env var is unset.
    """
    username = os.environ.get("IELTS_ADMIN_USER")
    password = os.environ.get("IELTS_ADMIN_PASSWORD")
    if not username or not password:
        return
    pass_hash = hash_password(password)
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (username, pass_hash, role) VALUES (?, ?, 'admin')",
            (username, pass_hash),
        )
    else:
        conn.execute(
            "UPDATE users SET pass_hash = ?, role = 'admin' WHERE id = ?",
            (pass_hash, row["id"]),
        )
    conn.commit()


def require_user(conn: sqlite3.Connection, token: str | None) -> dict:
    user = get_current_user(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def require_admin(conn: sqlite3.Connection, token: str | None) -> dict:
    user = require_user(conn, token)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限。")
    return user
```

- [ ] **Step 4: main.py 接线 ensure_admin**

`create_app()` 内、`init_db()` 之后加:

```python
    conn = connect()
    try:
        ensure_admin(conn)
    finally:
        conn.close()
```

顶部 import 加 `from auth import ensure_admin` 和 `from db import connect, init_db`(B1 已加 init_db,此处合并为一行)。

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_auth.py -v`
Expected: 10 PASS。

- [ ] **Step 6: Commit**

```bash
git add auth.py tests/test_auth.py main.py
git commit -m "feat: password hashing, sessions, and env-seeded admin bootstrap"
```

---

### Task B3:users_api.py — 登录/登出/me(无注册)

**Files:**
- Create: `users_api.py`
- Create: `tests/test_users_api.py`
- Modify: `main.py`(挂载路由)

**Interfaces:**
- Consumes: `auth.create_session/delete_session/get_current_user/verify_password`;`db.connect`
- Produces: APIRouter `users_api.router`,路由:
  - `POST /api/auth/login` body `{username, password}` → 200 `{username, role}` + Set-Cookie `ielts_session`(HttpOnly, SameSite=Lax, max_age=30d);401 用户名或密码错误。
  - `POST /api/auth/logout` → `{ok: true}` + 清 cookie。
  - `GET /api/auth/me` → 200 `{username, role}`;401 未登录。
  - 注册端点不存在(404)。
- 共享常量(供 admin_api 复用):`USERNAME_RE = ^[A-Za-z0-9_-]{2,32}$`、`MIN_PASSWORD_LEN = 6`。

- [ ] **Step 1: 写失败测试 tests/test_users_api.py**

```python
def test_register_endpoint_removed(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "anyone", "password": "secret123"},
    )
    assert resp.status_code == 404


def test_login_as_seeded_admin(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"username": "admin", "role": "admin"}
    assert client.get("/api/auth/me").json() == {"username": "admin", "role": "admin"}


def test_login_wrong_password_401(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong!!"},
    )
    assert resp.status_code == 401


def test_login_unknown_user_401(client):
    resp = client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "secret123"},
    )
    assert resp.status_code == 401


def test_me_without_login_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_flow(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
```

(admin 由 conftest 注入的 env 在 create_app 时播种。)

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_users_api.py -v`
Expected: FAIL(404,路由未挂载)。

- [ ] **Step 3: 实现 users_api.py**

```python
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
def logout(response: Response, token: str | None = Cookie(default=None)) -> dict:
    if token:
        conn = connect()
        try:
            delete_session(conn, token)
        finally:
            conn.close()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me(token: str | None = Cookie(default=None)) -> dict:
    conn = connect()
    try:
        user = get_current_user(conn, token)
    finally:
        conn.close()
    if user is None:
        raise HTTPException(status_code=401, detail="未登录。")
    return {"username": user["username"], "role": user["role"]}
```

- [ ] **Step 4: main.py 挂载路由**

`create_app()` 内加:

```python
    from users_api import router as users_router

    app.include_router(users_router)
```

(模块级 import 放顶部,create_app 内只 include。)

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_users_api.py -v`
Expected: 6 PASS。

- [ ] **Step 6: Commit**

```bash
git add users_api.py tests/test_users_api.py main.py
git commit -m "feat: login/logout/me endpoints, registration closed"
```

---

## Phase C:加权抽样

### Task C1:sampling.py — 纯抽样逻辑

**Files:**
- Create: `sampling.py`
- Create: `tests/test_sampling.py`

**Interfaces:**
- Consumes: `/api/data` payload 形状 `{"sections": {section: {part: [topic dict]}}}`(topic dict 含 `topic/questions/card/paired_topic/paired_part`)
- Produces:
  - `item_key(section, part, topic, text_or_None) -> str` = `f"{section}|{part}|{topic}|{text}"`
  - `sample_session(payload, section, part, count, recent, rng) -> (items, with_replacement, keys)`,其中 `recent: Counter[str]`(key→近 7 天出现次数),`rng: random.Random`。items 形状:`(topic, pairedTopic, pairedPart, text)` 元组或 `(topic, card)`;keys 与 items 一一对应,用于历史落库。
  - 常量 `DECAY = 0.25`、`FALLBACK_MIN_WEIGHT = 0.01`。
- 算法契约:
  - 权重 `w(k) = 0.25 ** recent[k]`;若 `max(w) < 0.01`(全部题近期被抽 ≥4 次)回退均匀权重 1.0。
  - P1/P3:主题权重 = 其问题权重之和 → 加权选主题 → 主题内加权不放回抽 count 题;不足放回补足。
  - P2:主题权重 = `0.25 ** recent[key]` → 加权不放回抽 count 主题;不足放回补足。
  - 无可用题目时返回 `((), False, ())`,由调用方报错。

- [ ] **Step 1: 写失败测试 tests/test_sampling.py**

```python
import random
from collections import Counter

import sampling

PAYLOAD = {
    "sections": {
        "S": {
            "P1": [
                {"topic": "T1", "questions": ["q1", "q2", "q3"], "card": None,
                 "paired_topic": "T1", "paired_part": "P1"},
                {"topic": "T2", "questions": ["q4", "q5", "q6"], "card": None,
                 "paired_topic": "T2", "paired_part": "P1"},
            ],
            "P2": [
                {"topic": "C1", "questions": [], "card": ["line1"],
                 "paired_topic": "C1", "paired_part": "P2"},
                {"topic": "C2", "questions": [], "card": ["line2"],
                 "paired_topic": "C2", "paired_part": "P2"},
            ],
            "P3": [],
        }
    }
}


def test_uniform_without_history():
    rng = random.Random(42)
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, Counter(), rng)
        seen[items[0]["text"]] += 1
    # 6 题均匀:每题出现次数在 333±80 内(种子固定,稳定)
    assert min(seen.values()) > 250
    assert max(seen.values()) < 420


def test_no_duplicates_within_session():
    rng = random.Random(7)
    for _ in range(100):
        items, with_repl, _ = sampling.sample_session(PAYLOAD, "S", "P1", 3, Counter(), rng)
        texts = [i["text"] for i in items]
        assert len(texts) == len(set(texts))
        assert with_repl is False


def test_recent_question_downweighted():
    rng = random.Random(9)
    recent = Counter({"S|P1|T1|q1": 10})
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, recent, rng)
        seen[items[0]["text"]] += 1
    # q1 权重 0.25^10 ≈ 1e-6,2000 次里几乎不可能抽到
    assert seen["q1"] <= 2


def test_all_recent_falls_back_to_uniform():
    rng = random.Random(11)
    recent = Counter({f"S|P1|T{i//3+1}|q{i}": 10 for i in range(1, 7)})
    seen = Counter()
    for _ in range(2000):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P1", 1, recent, rng)
        seen[items[0]["text"]] += 1
    assert min(seen.values()) > 250


def test_replacement_when_count_exceeds_pool():
    rng = random.Random(13)
    items, with_repl, _ = sampling.sample_session(PAYLOAD, "S", "P1", 5, Counter(), rng)
    assert len(items) == 5
    assert with_repl is True


def test_p2_recent_topic_downweighted():
    rng = random.Random(17)
    recent = Counter({"S|P2|C1|None": 8})
    seen = Counter()
    for _ in range(500):
        items, _, _ = sampling.sample_session(PAYLOAD, "S", "P2", 1, recent, rng)
        seen[items[0]["topic"]] += 1
    assert seen["C2"] > 400


def test_empty_section_returns_empty():
    rng = random.Random(19)
    payload = {"sections": {"S": {"P1": [], "P2": [], "P3": []}}}
    items, _, _ = sampling.sample_session(payload, "S", "P1", 2, Counter(), rng)
    assert items == ()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_sampling.py -v`
Expected: FAIL(no module named 'sampling')。

- [ ] **Step 3: 实现 sampling.py**

```python
"""Weighted sampling of the question bank, biased away from recently drawn items.

Pure logic: no I/O. `recent` is a Counter of item_key -> times drawn in the
window; weight per key is DECAY ** count, falling back to uniform when every
candidate was seen recently.
"""
import random
from collections import Counter

DECAY = 0.25
FALLBACK_MIN_WEIGHT = 0.01


def item_key(section: str, part: str, topic: str, text: str | None) -> str:
    return f"{section}|{part}|{topic}|{text}"


def _weights(keys: list[str], recent: Counter[str]) -> list[float]:
    weights = [DECAY ** recent.get(k, 0) for k in keys]
    if weights and max(weights) < FALLBACK_MIN_WEIGHT:
        return [1.0] * len(keys)
    return weights


def _sample_no_replacement(keys, weights, count, rng):
    picked = []
    pool = list(zip(keys, weights))
    while pool and len(picked) < count:
        ks = [k for k, _ in pool]
        ws = [w for _, w in pool]
        i = rng.choices(range(len(pool)), weights=ws, k=1)[0]
        picked.append(pool[i][0])
        pool.pop(i)
    return picked


def sample_session(payload, section, part, count, recent, rng):
    """Sample one session; returns (items, with_replacement, keys)."""
    topics = payload["sections"][section][part]

    if part == "P2":
        keys = [item_key(section, "P2", t["topic"], None) for t in topics]
        weights = _weights(keys, recent)
        picked = _sample_no_replacement(keys, weights, count, rng)
        picked += [rng.choices(keys, weights=weights, k=1)[0]
                   for _ in range(count - len(picked))]
        by_key = {item_key(section, "P2", t["topic"], None): t for t in topics}
        items = tuple({"topic": by_key[k]["topic"], "card": by_key[k]["card"]}
                      for k in picked)
        return items, count > len(keys), picked

    topic_infos = []
    for t in topics:
        questions = [q for q in t["questions"] if q]
        if not questions:
            continue
        keys = [item_key(section, part, t["topic"], q) for q in questions]
        weights = _weights(keys, recent)
        topic_infos.append((t, questions, keys, weights, sum(weights)))
    if not topic_infos:
        return (), False, ()

    chosen = rng.choices(topic_infos, weights=[ti[4] for ti in topic_infos], k=1)[0]
    t, questions, keys, weights, _ = chosen
    picked = _sample_no_replacement(keys, weights, count, rng)
    picked += [rng.choices(keys, weights=weights, k=1)[0]
               for _ in range(count - len(picked))]
    text_by_key = dict(zip(keys, questions))
    items = tuple(
        {"topic": t["topic"], "pairedTopic": t["paired_topic"],
         "pairedPart": t["paired_part"], "text": text_by_key[k]}
        for k in picked
    )
    return items, count > len(keys), picked
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_sampling.py -v`
Expected: 7 PASS(若统计断言边界紧张,可微调测试边界值,算法不动)。

- [ ] **Step 5: Commit**

```bash
git add sampling.py tests/test_sampling.py
git commit -m "feat: recency-weighted sampling with uniform fallback"
```

---

### Task C2:session_api.py — POST /api/session

**Files:**
- Create: `session_api.py`
- Create: `tests/test_session_api.py`
- Modify: `main.py`(挂载)

**Interfaces:**
- Consumes: `sampling.sample_session`;`auth.get_current_user`;`db.connect`
- Produces: `create_session_router(payload: dict) -> APIRouter`,路由 `POST /api/session`:
  - body `{section: str, part: str, count: int}`;Cookie 可选。
  - 422:`题库数据缺失,请刷新页面重试。`/`题型无效。`/`题目数量需为 1–10 的整数。`/`该类别暂无可用题目。`(与前端 validateConfig 文案一致)
  - 200:`{items, withReplacement}`。登录用户:抽样前读近 7 天 `Counter`,抽样后把 keys 写入 history(一次 executemany+commit)。

- [ ] **Step 1: 写失败测试 tests/test_session_api.py**

```python
from collections import Counter

import db


def _login(client):
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    ).status_code == 200


def test_session_anonymous_uniform_ok(client):
    resp = client.post(
        "/api/session",
        json={"section": "大陆新题", "part": "P1", "count": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert all({"topic", "pairedTopic", "pairedPart", "text"} <= set(i) for i in body["items"])
    assert body["withReplacement"] is False


def test_session_validation_422(client):
    assert client.post("/api/session", json={"section": "不存在", "part": "P1", "count": 2}).status_code == 422
    assert client.post("/api/session", json={"section": "大陆新题", "part": "P9", "count": 2}).status_code == 422
    assert client.post("/api/session", json={"section": "大陆新题", "part": "P1", "count": 99}).status_code == 422


def test_session_records_history_for_logged_in_user(client):
    _login(client)
    client.post("/api/session", json={"section": "大陆新题", "part": "P1", "count": 2})
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM history").fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert rows[0]["user_id"] == 1
    assert rows[0]["item_key"].startswith("大陆新题|P1|")


def test_session_no_history_when_anonymous(client):
    client.post("/api/session", json={"section": "大陆新题", "part": "P1", "count": 2})
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"]
    finally:
        conn.close()
    assert n == 0


def test_session_avoids_recent_questions_when_logged_in(client):
    _login(client)
    seen = Counter()
    for _ in range(10):
        resp = client.post(
            "/api/session",
            json={"section": "大陆新题", "part": "P1", "count": 1},
        )
        seen[resp.json()["items"][0]["text"]] += 1
    # 大陆新题 P1 题库题量远大于 10,避重下重复率应低(保守断言:单一题不超过 5 次)
    assert max(seen.values()) <= 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_session_api.py -v`
Expected: FAIL(404,路由未挂载)。

- [ ] **Step 3: 实现 session_api.py**

```python
"""POST /api/session — server-side weighted sampling + history recording."""
import random
from collections import Counter

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db import connect
from sampling import sample_session

PART_ORDER = ("P1", "P2", "P3")


class SessionRequest(BaseModel):
    section: str
    part: str
    count: int


def create_session_router(payload: dict) -> APIRouter:
    router = APIRouter()

    @router.post("/api/session")
    def api_session(body: SessionRequest, token: str | None = Cookie(default=None)) -> dict:
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
            user = get_current_user(conn, token)
            if user is None:
                recent = Counter()
            else:
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

            if user is not None and keys:
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
```

- [ ] **Step 4: main.py 挂载**

`create_app()` 内(users_router include 之后)加:

```python
    from session_api import create_session_router

    app.include_router(create_session_router(payload))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_session_api.py -v`
Expected: 5 PASS。

- [ ] **Step 6: Commit**

```bash
git add session_api.py tests/test_session_api.py main.py
git commit -m "feat: /api/session server-side sampling with per-user history"
```

---

## Phase D:管理后台

### Task D1:admin_api.py — 用户管理与统计

**Files:**
- Create: `admin_api.py`
- Create: `tests/test_admin_api.py`
- Modify: `main.py`(挂载)

**Interfaces:**
- Consumes: `auth.require_admin/hash_password`;`users_api.USERNAME_RE/MIN_PASSWORD_LEN`;`db.connect`
- Produces: APIRouter `admin_api.router`:
  - `GET /api/admin/users` → `{users: [{id, username, role, created_at, draws_total, draws_7d}]}`(draws_7d 无记录时为 0)
  - `POST /api/admin/users` body `{username, password, role}` → `{ok: true}`;409/422
  - `DELETE /api/admin/users/{user_id}` → `{ok: true}`;不能删自己(400);404
  - `POST /api/admin/users/{user_id}/password` body `{password}` → `{ok: true}`;同时吊销该用户全部会话;404/422
  - 全部接口 require_admin(401/403)。

- [ ] **Step 1: 写失败测试 tests/test_admin_api.py**

```python
def _admin_login(client):
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    ).status_code == 200


def _create_user(client, name, password="secret123", role="user"):
    return client.post(
        "/api/admin/users",
        json={"username": name, "password": password, "role": role},
    )


def test_non_admin_forbidden(client):
    _admin_login(client)
    _create_user(client, "bob")
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "bob", "password": "secret123"})
    assert client.get("/api/admin/users").status_code == 403
    assert _create_user(client, "carol").status_code == 403


def test_admin_list_users_with_stats(client):
    _admin_login(client)
    client.post("/api/session", json={"section": "大陆新题", "part": "P1", "count": 2})
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert users[0]["username"] == "admin"
    assert users[0]["role"] == "admin"
    assert users[0]["draws_total"] == 2
    assert users[0]["draws_7d"] == 2


def test_admin_create_delete_user(client):
    _admin_login(client)
    resp = _create_user(client, "carol")
    assert resp.status_code == 200
    users = client.get("/api/admin/users").json()["users"]
    carol = next(u for u in users if u["username"] == "carol")
    assert client.delete(f"/api/admin/users/{carol['id']}").status_code == 200
    assert all(
        u["username"] != "carol"
        for u in client.get("/api/admin/users").json()["users"]
    )


def test_admin_cannot_delete_self(client):
    _admin_login(client)
    boss = client.get("/api/admin/users").json()["users"][0]
    assert client.delete(f"/api/admin/users/{boss['id']}").status_code == 400


def test_admin_reset_password_revokes_sessions(client):
    _admin_login(client)
    _create_user(client, "bob")
    bob = next(
        u for u in client.get("/api/admin/users").json()["users"]
        if u["username"] == "bob"
    )
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "bob", "password": "secret123"}
    ).status_code == 200
    client.post("/api/auth/logout")
    _admin_login(client)
    resp = client.post(
        f"/api/admin/users/{bob['id']}/password",
        json={"password": "newpass456"},
    )
    assert resp.status_code == 200
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "bob", "password": "secret123"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "bob", "password": "newpass456"}
    ).status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_admin_api.py -v`
Expected: FAIL(404,路由未挂载)。

- [ ] **Step 3: 实现 admin_api.py**

```python
"""Admin endpoints: user management and practice stats (admin role only)."""
from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import hash_password, require_admin
from db import connect
from users_api import MIN_PASSWORD_LEN, USERNAME_RE

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class PasswordReset(BaseModel):
    password: str


@router.get("/api/admin/users")
def list_users(token: str | None = Cookie(default=None)) -> dict:
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
def create_user(body: UserCreate, token: str | None = Cookie(default=None)) -> dict:
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
def delete_user(user_id: int, token: str | None = Cookie(default=None)) -> dict:
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
def reset_password(user_id: int, body: PasswordReset, token: str | None = Cookie(default=None)) -> dict:
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
```

- [ ] **Step 4: main.py 挂载**

create_app 内加:

```python
    from admin_api import router as admin_router

    app.include_router(admin_router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_admin_api.py -v`
Expected: 5 PASS。

- [ ] **Step 6: Commit**

```bash
git add admin_api.py tests/test_admin_api.py main.py
git commit -m "feat: admin user management and stats endpoints"
```

---

### Task D2:admin.html + admin.js + admin.css — 管理页

**Files:**
- Create: `static/admin.html`
- Create: `static/admin.js`
- Create: `static/admin.css`
- Modify: `static/style.css`(仅补 `.input` 通用样式,admin 页也引用)

**Interfaces:**
- Consumes: `/api/admin/users`(GET/POST/DELETE)、`/api/admin/users/{id}/password`、`/api/auth/me`、`/api/auth/logout`;复用 `static/auth.js` 的 `fetchMe/logout`(Task E1)。
- **执行顺序:本任务与 E1 同批执行,或 E1 先行**(admin.js import auth.js)。
- 页面行为:打开即 `fetchMe` → 未登录跳回 `/`;非 admin 显示「无权限」;admin 渲染用户表(用户名/角色/7天抽题/总抽题/创建时间/操作),建号表单(用户名/密码/角色 select),每行「重置密码」(prompt 新密码)、「删除」(confirm)。错误显示在页内 error 区。

- [ ] **Step 1: 写 admin.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>管理后台 · 雅思口语随机练习</title>
  <link rel="stylesheet" href="style.css">
  <link rel="stylesheet" href="admin.css">
</head>
<body>
  <div class="app">
    <header class="masthead">
      <p class="masthead__kicker">IELTS SPEAKING · 管理后台</p>
      <h1 class="masthead__title">用户管理</h1>
      <p class="masthead__note">建号、重置密码、查看练习统计。</p>
    </header>
    <main>
      <div class="adminbar">
        <span class="adminbar__user" id="adminUser"></span>
        <a class="btn btn--ghost btn--small" href="/">← 回练习页</a>
        <button class="btn btn--ghost btn--small" id="adminLogout">退出登录</button>
      </div>
      <p class="error" id="adminError" role="alert" hidden></p>

      <section class="panel" id="adminDenied" hidden>
        <p>当前账号没有管理员权限。<a href="/">回练习页</a></p>
      </section>

      <section class="panel" id="adminMain" hidden>
        <h2 class="admin-h2">新建用户</h2>
        <form class="admin-form" id="createForm">
          <input class="input" id="newName" placeholder="用户名" autocomplete="off">
          <input class="input" id="newPass" type="password" placeholder="密码(至少 6 位)" autocomplete="new-password">
          <select class="input" id="newRole">
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
          <button class="btn" type="submit">创建</button>
        </form>

        <h2 class="admin-h2">用户列表</h2>
        <table class="atable">
          <thead>
            <tr><th>用户名</th><th>角色</th><th>7 天抽题</th><th>总抽题</th><th>创建时间</th><th>操作</th></tr>
          </thead>
          <tbody id="userRows"></tbody>
        </table>
      </section>
    </main>
  </div>
  <script type="module" src="admin.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 admin.js**

```js
import { fetchMe, logout } from "./auth.js";

const $ = (id) => document.getElementById(id);
const els = {
  user: $("adminUser"),
  logout: $("adminLogout"),
  error: $("adminError"),
  denied: $("adminDenied"),
  main: $("adminMain"),
  form: $("createForm"),
  name: $("newName"),
  pass: $("newPass"),
  role: $("newRole"),
  rows: $("userRows"),
};

function setError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

async function loadUsers() {
  const resp = await fetch("/api/admin/users");
  if (resp.status === 401) {
    location.href = "/";
    return;
  }
  if (resp.status === 403) {
    els.denied.hidden = false;
    return;
  }
  if (!resp.ok) {
    setError("加载用户列表失败。");
    return;
  }
  const { users } = await resp.json();
  els.rows.replaceChildren();
  for (const u of users) {
    const tr = document.createElement("tr");
    const cells = [
      u.username,
      u.role === "admin" ? "管理员" : "普通用户",
      String(u.draws_7d),
      String(u.draws_total),
      (u.created_at || "").replace("T", " ").slice(0, 16),
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    const td = document.createElement("td");
    const resetBtn = document.createElement("button");
    resetBtn.className = "btn btn--small";
    resetBtn.textContent = "重置密码";
    resetBtn.addEventListener("click", async () => {
      const password = prompt(`为 ${u.username} 设置新密码(至少 6 位):`);
      if (!password) return;
      const r = await fetch(`/api/admin/users/${u.id}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      setError(r.ok ? "" : "重置失败,请检查输入。");
      if (r.ok) loadUsers();
    });
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn--danger btn--small";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", async () => {
      if (!confirm(`确认删除用户 ${u.username}?其练习记录将一并删除。`)) return;
      const r = await fetch(`/api/admin/users/${u.id}`, { method: "DELETE" });
      setError(r.ok ? "" : "删除失败。");
      loadUsers();
    });
    td.appendChild(resetBtn);
    td.appendChild(delBtn);
    tr.appendChild(td);
    els.rows.appendChild(tr);
  }
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  setError("");
  const resp = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: els.name.value,
      password: els.pass.value,
      role: els.role.value,
    }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    setError(j.detail || "创建失败。");
    return;
  }
  els.name.value = "";
  els.pass.value = "";
  loadUsers();
});

els.logout.addEventListener("click", async () => {
  await logout();
  location.href = "/";
});

async function init() {
  const me = await fetchMe();
  if (!me) {
    location.href = "/";
    return;
  }
  els.user.textContent = `当前:${me.username} (${me.role === "admin" ? "管理员" : "普通用户"})`;
  if (me.role !== "admin") {
    els.denied.hidden = false;
    return;
  }
  els.main.hidden = false;
  loadUsers();
}

init();
```

- [ ] **Step 3: 写 admin.css**

```css
/* 管理后台页专用样式(叠加在 style.css 之上) */
.adminbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}
.adminbar__user { color: var(--muted, #9db3a6); font-size: 0.9rem; }
.admin-h2 {
  font-family: var(--font-display, "Songti SC", serif);
  font-size: 1.15rem;
  margin: 1.5rem 0 0.75rem;
  color: var(--accent, #e0a03c);
}
.admin-form { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.atable {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.95rem;
}
.atable th, .atable td {
  text-align: left;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--line, #3a5249);
}
.atable th { color: var(--muted, #9db3a6); font-weight: normal; }
.atable .btn + .btn { margin-left: 0.5rem; }
```

(变量名沿用 style.css 现有 CSS 变量;若名称不同,实现时对齐 style.css 实际变量。)

- [ ] **Step 4: style.css 补通用输入框样式**

style.css 末尾追加:

```css
/* 登录/管理表单输入框 */
.input {
  background: var(--surface, #1b2d28);
  color: var(--paper, #f2ead7);
  border: 1px solid var(--line, #3a5249);
  border-radius: 6px;
  padding: 0.55rem 0.8rem;
  font-size: 0.95rem;
  font-family: inherit;
}
.input:focus { outline: 2px solid var(--accent, #e0a03c); outline-offset: 1px; }
```

(具体变量以 style.css 现值为准。)

- [ ] **Step 5: 手工验证**

Playwright 打开 `http://127.0.0.1:8000/admin.html`:
1. 未登录 → 跳回 `/`。
2. 登录普通用户访问 → 显示「无权限」。
3. 管理员访问 → 列表可见;建号成功出现在列表;重置密码后该用户旧会话失效;删除用户生效;删除自己报错提示。

- [ ] **Step 6: Commit**

```bash
git add static/admin.html static/admin.js static/admin.css static/style.css
git commit -m "feat: admin panel page for user management and stats"
```

---

## Phase E:前端整合

### Task E1:auth.js + index.html 登录区(仅登录)

**Files:**
- Create: `static/auth.js`
- Modify: `static/index.html`(authbar + authform,无注册按钮)
- Modify: `static/style.css`(authbar/authform 样式)

**Interfaces:**
- Produces(供 app.js、admin.js 复用):
  - `fetchMe() -> Promise<{username, role} | null>`
  - `login(username, password) -> Promise<{username, role}>`(失败 throw Error(detail))
  - `logout() -> Promise<void>`
  - `refreshAuthUI(els) -> Promise<void>`:els = `{authUser, authLoginBtn, authAdminBtn, authLogoutBtn}`,按登录态显隐。

- [ ] **Step 1: 写 auth.js**

```js
// Auth helpers + UI state, shared by index page and admin page.

export async function fetchMe() {
  try {
    const resp = await fetch("/api/auth/me");
    if (!resp.ok) return null;
    return await resp.json(); // {username, role}
  } catch {
    return null;
  }
}

export async function login(username, password) {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    throw new Error(j.detail || "登录失败,请重试。");
  }
  return await resp.json();
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
}

// els: {authUser, authLoginBtn, authAdminBtn, authLogoutBtn} — 全部可选
export async function refreshAuthUI(els) {
  const me = await fetchMe();
  const loggedIn = Boolean(me);
  if (els.authUser) {
    els.authUser.hidden = !loggedIn;
    if (me) els.authUser.textContent = `${me.username}${me.role === "admin" ? " · 管理员" : ""}`;
  }
  if (els.authLoginBtn) els.authLoginBtn.hidden = loggedIn;
  if (els.authAdminBtn) els.authAdminBtn.hidden = !(loggedIn && me.role === "admin");
  if (els.authLogoutBtn) els.authLogoutBtn.hidden = !loggedIn;
}
```

- [ ] **Step 2: index.html 加登录区(仅登录,无注册)**

`masthead` 之后、`nav.tabs` 之前插入:

```html
<div class="authbar">
  <span class="authbar__user" id="authUser" hidden></span>
  <button class="btn btn--ghost btn--small" id="authLoginBtn">登录</button>
  <a class="btn btn--ghost btn--small" id="authAdminBtn" href="/admin.html" hidden>管理后台</a>
  <button class="btn btn--ghost btn--small" id="authLogoutBtn" hidden>退出</button>
</div>
<div class="authform" id="authForm" hidden>
  <input class="input" id="authName" placeholder="用户名" autocomplete="username">
  <input class="input" id="authPass" type="password" placeholder="密码" autocomplete="current-password">
  <button class="btn" id="authLoginSubmit">登录</button>
  <p class="error" id="authError" role="alert" hidden></p>
</div>
```

- [ ] **Step 3: style.css 加 authbar/authform 样式**

```css
/* 登录区 */
.authbar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}
.authbar__user { color: var(--muted); font-size: 0.9rem; }
.authform {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 1rem;
}
.btn--small { padding: 0.35rem 0.7rem; font-size: 0.85rem; }
```

(`--muted` 若不存在,用现有同义变量或新加 `--muted: #9db3a6`。)

- [ ] **Step 4: 手工验证**

Playwright 打开首页:未登录显示「登录」按钮 → 点开表单 → 输入 admin 账号登录 → 显示「admin · 管理员」+「管理后台」链接 → 退出恢复「登录」。控制台无报错。

- [ ] **Step 5: Commit**

```bash
git add static/auth.js static/index.html static/style.css
git commit -m "feat: login bar on main page, registration closed"
```

---

### Task E2:app.js 接 /api/session + 登录态

**Files:**
- Modify: `static/app.js`

**Interfaces:**
- Consumes: `POST /api/session`(Task C2);`./auth.js`(Task E1)
- 行为:登录态 → 服务端加权抽样并记历史;未登录 → 服务端均匀抽样;网络/服务错误 → 回退本地 `prepareSession`(sampler.js)。422 显示配置错误。

- [ ] **Step 1: import auth 模块**

app.js 顶部加:

```js
import { login, logout, refreshAuthUI } from "./auth.js";
```

- [ ] **Step 2: els 加认证 UI 引用**

```js
  authUser: $("authUser"),
  authLoginBtn: $("authLoginBtn"),
  authAdminBtn: $("authAdminBtn"),
  authLogoutBtn: $("authLogoutBtn"),
  authForm: $("authForm"),
  authName: $("authName"),
  authPass: $("authPass"),
  authLoginSubmit: $("authLoginSubmit"),
  authError: $("authError"),
```

- [ ] **Step 3: 加登录 UI 处理器 + 初始化**

文件末尾加:

```js
// ── 登录区 ──────────────────────────────────────────────────
function setAuthError(msg) {
  els.authError.textContent = msg;
  els.authError.hidden = !msg;
}

els.authLoginBtn.addEventListener("click", () => {
  els.authForm.hidden = !els.authForm.hidden;
});

els.authLoginSubmit.addEventListener("click", async () => {
  setAuthError("");
  try {
    await login(els.authName.value.trim(), els.authPass.value);
    els.authForm.hidden = true;
    els.authName.value = "";
    els.authPass.value = "";
    await refreshAuthUI(els);
  } catch (err) {
    setAuthError(err.message);
  }
});

els.authLogoutBtn.addEventListener("click", async () => {
  await logout();
  await refreshAuthUI(els);
});

refreshAuthUI(els);
```

- [ ] **Step 4: startSession 改用 /api/session**

`startSession` 中 `const prep = prepareSession(data, cfg);` 及其错误处理替换为:

```js
  let prep;
  try {
    prep = await fetchSession({ section: session.section, part: session.part, count });
  } catch (err) {
    if (err.status === 422) {
      setError(err.message);
      return;
    }
    // 服务不可用:回退本地均匀抽样,保证离线兜底
    prep = prepareSession(data, { section: session.section, part: session.part, count });
    if (prep.error) {
      setError(prep.error);
      return;
    }
  }
```

并在 `startSession` 之前新增:

```js
async function fetchSession(cfg) {
  const resp = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    const err = new Error(j.detail || "抽题失败,请重试。");
    err.status = resp.status;
    throw err;
  }
  return await resp.json();
}
```

注意:服务端 422 文案与 `validateConfig` 一致,前端 `validateConfig(data, cfg)` 仍保留先行校验(即时反馈);服务端校验是边界兜底。

- [ ] **Step 5: 手工验证**

1. 未登录开始练习 → 正常抽题(服务端均匀)。
2. 登录后开始 → 正常抽题;连抽 3 轮观察题目重复率明显降低(与改前对比)。
3. 停掉后端再开始 → 本地回退仍能抽题(但 TTS 也会失败,仅验证抽题路径)。
4. 登录后开始 → `/api/admin/users` 统计 draws 增加。

- [ ] **Step 6: Commit**

```bash
git add static/app.js
git commit -m "feat: use /api/session for weighted sampling with local fallback"
```

---

### Task E3:sampler.js 保留 + 最终回归

**Files:**
- Modify: `static/sampler.js`(预期零改动)

**说明:** `prepareSession` 保留为离线回退(E2),`shuffle/randInt` 仍被其使用 → **sampler.js 实际零改动**。本任务只做回归确认。

- [ ] **Step 1: 全量跑后端测试**

Run: `uv run pytest -v`
Expected: 全部 PASS(test_db/test_auth/test_users_api/test_sampling/test_session_api/test_admin_api)。

- [ ] **Step 2: Playwright 端到端回归(桌面 + 移动视口)**

- 未登录:开始 → 暂停/继续 → 重听 → 停止 → 再来一轮。
- 登录:练习一轮 → 管理后台看统计。
- 移动 375px 视口:登录区、暂停按钮、管理表格不溢出。

- [ ] **Step 3: Commit(如有改动)**

```bash
git add -A
git commit -m "chore: final regression pass"
```

---

## Phase F:文档与部署

### Task F1:文档与环境变量

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: .env.example 追加**

```
# 管理员账号(启动时自动创建/同步;留空则无管理员)
IELTS_ADMIN_USER=
IELTS_ADMIN_PASSWORD=

# SQLite 数据库路径(默认:项目根目录 ielts.db)
IELTS_DB=
```

- [ ] **Step 2: .gitignore 追加**

```
# 用户数据库
ielts.db
```

- [ ] **Step 3: README.md 更新**

「功能」加:暂停/继续、避重加权抽题、用户账号与练习统计、管理后台。
「环境变量」表加 `IELTS_ADMIN_USER`、`IELTS_ADMIN_PASSWORD`、`IELTS_DB`。
新「账号」节:

```
## 账号

- 不开放公开注册:普通账号由管理员在 /admin.html 后台创建。
- 管理员账号由环境变量 IELTS_ADMIN_USER / IELTS_ADMIN_PASSWORD 注入,
  服务启动时自动创建或同步(缺则建、同名存在则提权并重置密码)。
- 未登录也可使用随机练习(均匀抽样);登录后启用避重抽样并记录练习历史。
- 密码使用 PBKDF2-SHA256(20 万次迭代)哈希存储,登录态为 HttpOnly Cookie。
```

(README 不写任何真实密码。)

- [ ] **Step 4: Commit**

```bash
git add .env.example .gitignore README.md
git commit -m "docs: accounts, admin panel, admin env bootstrap"
```

---

### Task F2:VPS 部署与线上验证

**Files:** 本地 `.env`(gitignored);VPS `.env`

- [ ] **Step 1: 本地 .env 追加管理员凭据**

本地 `/Users/ian/workplace/ielts_speak/.env` 追加:

```
IELTS_ADMIN_USER=ian1274
IELTS_ADMIN_PASSWORD=Yyx991274
```

(.env 已被 gitignore,不会进仓库。)

- [ ] **Step 2: 推送代码**

```bash
git push origin main
```

- [ ] **Step 3: VPS 拉取、写 .env、重启**

```bash
ssh -p 10540 root@218.11.5.114 "cd /opt/ielts-speak && git pull && uv sync && \
printf '\nIELTS_ADMIN_USER=ian1274\nIELTS_ADMIN_PASSWORD=Yyx991274\n' >> .env && \
systemctl restart ielts-speak && sleep 2 && systemctl is-active ielts-speak"
```

注意:VPS 已有 .env(QWEN 密钥),追加不覆盖。若之前已写过 IELTS_ADMIN_* 行则用 `grep -q` 判断避免重复。
Expected: `active`。

- [ ] **Step 4: 内网接口验证**

```bash
ssh -p 10540 root@218.11.5.114 "curl -s http://127.0.0.1:8000/health"
ssh -p 10540 root@218.11.5.114 "curl -s -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"ian1274\",\"password\":\"Yyx991274\"}' -c /tmp/ck.txt"
ssh -p 10540 root@218.11.5.114 "curl -s -b /tmp/ck.txt http://127.0.0.1:8000/api/auth/me"
ssh -p 10540 root@218.11.5.114 "curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/api/session -H 'Content-Type: application/json' -d '{\"section\":\"大陆新题\",\"part\":\"P1\",\"count\":2}'"
ssh -p 10540 root@218.11.5.114 "curl -s -b /tmp/ck.txt http://127.0.0.1:8000/api/admin/users"
```

Expected:health `ok`;login 返回 `{"username":"ian1274","role":"admin"}`;me 返回 admin;session 返回 2 个 items;users 返回列表含 draws 计数。

- [ ] **Step 5: 外网验证(两个端口映射)**

浏览器打开 `http://218.11.5.114:10607/` 与 `http://111.62.241.72:10169/`:
1. 首页正常;登录 ian1274。
2. 开始一轮 P1,暂停/继续/重听/停止均正常。
3. `/admin.html` 正常显示统计,建号/删号可用。

- [ ] **Step 6: 记录**

TODO.md 状态更新(部署信息加账号说明)。

---

## Self-Review

**1. Spec coverage:**
- 暂停键 → Task A1/A2/A3 ✓
- 避重加权抽样 → Task C1/C2(服务端)+ E2(前端接入)✓
- 用户管理(关闭注册、管理员 env 注入、后台建号)→ Task B1-B3、D1-D2、E1 ✓
- 管理员账号 ian1274 → B2(ensure_admin)+ F2(.env 注入)✓
- 随机性「如何」诊断 → 需求节第 2 条已写明现状与原因 ✓

**2. Placeholder scan:** 无 TBD/TODO;所有代码步骤含完整代码。admin.css 的 CSS 变量名需与 style.css 现有变量对齐(已注明)。

**3. Type consistency:**
- `sample_session(...) -> (items, with_replacement, keys)` — C1 定义、C2 使用一致 ✓
- `get_current_user` 返回 `{id, username, role}` — B2 定义、B3/C2/D1 使用一致 ✓
- 前端 items 形状 `pairedTopic/pairedPart` — C1 输出与现有 renderItem 消费一致 ✓
- auth.js 导出 `fetchMe/login/logout/refreshAuthUI` — E1 定义、D2/E2 使用一致 ✓
- conftest 注入 `IELTS_ADMIN_USER=admin/IELTS_ADMIN_PASSWORD=secret123`,B3/C2/D1 测试登录依赖此约定 ✓
- 执行顺序:D2(admin.js)依赖 E1(auth.js),同批或 E1 先行(已注明)✓

**4. 已知限制(记录,不在本次修复):**
- 暂停按钮快速双击(语音阶段暂停→立即继续)可能导致该题不重读直接进入倒计时。影响小,接受。
- Cookie 未加 `Secure` 标志:线上为 HTTP 端口映射(非 HTTPS),加 Secure 会导致无法登录。若日后上 HTTPS 需补。
- `item_key` 用 `|` 拼接,主题名含 `|` 会歧义;当前题库主题名均为中文,无此字符。
- 管理员密码与 VPS SSH 密码相同,属用户自选;如需收紧可改 .env 后重启(启动时自动同步)。
