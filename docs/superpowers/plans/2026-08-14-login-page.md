# 独立登录页 + 强制登录改造

## 背景

- 现状:首页内嵌登录表单,匿名用户可直接练习(均匀随机、不记历史)。
- 用户决定:**强制登录** — 未登录一律跳 `/login.html`,有账号才能用。贴合卖号商业模式。
- 调研结论(通行做法):独立 `/login` 页;登录后跳 `?next=` 校验后的原地址,无 `next` 跳首页;未登录访问受保护页 → `/login?next=<原URL>`;防 open-redirect(只允许站内相对路径);HttpOnly cookie 30 天(已有)。

## 设计决策

| 项 | 决策 |
|---|---|
| 登录页 | 新增独立 `static/login.html` + `login.css` + `login.js` |
| 强制范围 | 前端页面全部;后端 `/api/data`、`/api/voices`、`/api/tts`、`/api/session` 全部要求登录(匿名不再可练) |
| 公开端点 | `/health`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/me`(401 用)、`login.html` 及其静态资源 |
| 跳转 | 登录成功 → `?next=`(校验:以 `/` 开头、不以 `//` 开头、不含 `\`、不含 `:`),否则 `/` |
| 登出 | 登出后跳 `/login.html` |
| index.html | 删内嵌登录表单;authbar 保留「用户名 + 管理后台 + 退出」;页面加载 fetchMe 401 → `/login.html?next=/` |
| admin.html | 未登录 → `/login.html?next=/admin.html`(现跳 `/`);非管理员仍显示无权限面板 |

## 任务

### A. 后端:受保护端点收口

1. `main.py`:`/api/data`、`/api/voices`、`/api/tts` 加 `require_user` 依赖。
2. `session_api.py`:`/api/session` 从「auth-optional」改为 `require_user`;移除匿名分支(匿名不再产生历史,也不需要)。`sample_session` 的 `recent` 逻辑不变,只是 user 恒存在。
3. 更新测试:
   - `test_session_api.py`:匿名请求 → 401(原 `test_session_anonymous_uniform_ok` 改为 401 断言);`test_session_no_history_when_anonymous` 删除。
   - 新增 `test_data_voices_tts_require_login`:三个端点匿名 401、登录后 200(/api/tts 用假 text 至少验证 401 路径)。
4. `uv run pytest` 全绿。

### B. login.html / login.js / login.css

1. `static/login.html`:同款 masthead 视觉 + 居中卡片:用户名、密码、「登录」按钮、错误行;无注册入口;`<script type="module" src="login.js">`;标题「登录 · 雅思口语随机练习」。
2. `static/login.js`:
   - `nextParam()`:读 `?next=`,校验安全(以 `/` 开头、不以 `//` 开头、不含 `\`/`:`),非法或空 → `/`。
   - 提交 → `login()`(auth.js 复用)→ `location.href = nextParam()`。
   - 已登录访问登录页 → 直接跳走(`fetchMe()` 200 → redirect)。
3. `static/login.css`:卡片居中、移动端适配(390px 宽测试)。

### C. index.html / app.js 收口

1. `index.html`:删 `#authForm` 区块;authbar 保留 `#authUser` / `#authAdminBtn` / `#authLogoutBtn`,删 `#authLoginBtn`。
2. `app.js`:
   - 删 `#authForm` 相关 els 和登录提交逻辑。
   - 启动时 `refreshAuthUI(els)` 前先 `fetchMe()`:401 → `location.href = "/login.html?next=/"`;登录态则正常渲染。
   - `refreshAuthUI` 里 me 为 null 时同样重定向(集中处理)。
   - 登出 handler:logout 后 → `location.href = "/login.html"`。
3. `admin.js`:`init()` 401 分支从 `location.href = "/"` 改为 `"/login.html?next=/admin.html"`。

### D. 验证(本机)

1. `uv run pytest -v` 全绿。
2. Playwright 桌面 + 移动端:
   - 匿名访问 `/` → 重定向 `/login.html`;登录页可见、无注册入口。
   - 登录 ian1274 → 跳回 `/`;authbar 显示「ian1274 · 管理员」+ 管理后台链接。
   - 错误密码 → 错误提示、停留登录页。
   - 匿名访问 `/admin.html` → 登录页;登录后回 `/admin.html` 显示用户列表。
   - open-redirect:登录页带 `?next=http://evil.com` 登录 → 跳 `/`(不回外部)。
   - 退出 → 回登录页;再访问 `/` → 又跳登录页。
   - 移动端 390×844:登录页布局无横向滚动、登录流程通。

### E. 上线

1. 提交(分 commit:后端收口 / 登录页 / 首页与 admin 收口)。
2. push → VPS `/opt/ielts-speak` pull + `uv sync` + restart(EnvironmentFile 已修)。
3. 外网验证:218.11.5.114:10607 与 111.62.241.72:10169 — 匿名访问 `/` 跳登录页、登录成功回首页、练习正常、admin 正常。
4. TODO.md 记录。
