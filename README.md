# IELTS Speaking 随机练习

按真实考试节奏随机抽题练习雅思口语。P1/P3 用 TTS 语音提问 (可重听),P2 显示英文题卡;考前计时用考场挂钟模拟。

题库:2026 年 5–8 月 (大陆新题 / 大陆老题 / 非大陆新题)。

## 功能

- **P1 / P2 / P3 三档** tab 切换
- **随机抽题**:先随机选主题 (Music、喜欢或不喜欢的高建筑…),再在主题下抽指定数量问题;登录用户按 7 天内已抽题避重加权 (抽过越多次,再出现概率越低)
- **中途暂停**:暂停即冻结倒计时并打断语音,继续后从剩余时间接续;若语音未播完被暂停,恢复时重读当前题
- **可配置**:题数 (1–10,默认 2)、停顿 (5–300s,默认 120s)、发音人 (Jennifer / Ryan)、语速 (0.8 / 1.0 / 1.2)
- **P1/P3**:TTS 语音提问 (阿里云 qwen3-tts-flash),🔊 重听按钮;查看题目显示主题 + 英文题目
- **P2**:英文题卡开始即显示,点击「显示主题」才显示中文主题
- **考场挂钟**:指针一圈 = 一题作答时长,最后 10 秒变信号红
- **移动端适配**:操作栏吸底、大按钮、安全区避让
- TTS 磁盘缓存 (`.cache/tts/`),重复文本秒回
- **账号系统**:独立登录页,所有页面和接口强制登录;登录后按人记录抽题历史;管理员在 `/admin.html` 建号、重置密码、查看练习统计

## 技术栈

- FastAPI + uvicorn (Python 3.12, uv 管理)
- 原生 HTML/CSS/JS 前端 (无构建)
- TTS:阿里云百炼 qwen3-tts-flash HTTP API (MaaS 业务空间专属域名)
- 浏览器 speechSynthesis 兜底

## 本地运行

```bash
uv sync
cp .env.example .env   # 填入 QWEN_APIKEY
uv run uvicorn main:app --port 8000
```

打开 http://localhost:8000

## 部署 (systemd)

```bash
git clone <repo> /opt/ielts-speak
cd /opt/ielts-speak && uv sync --frozen
cp .env /opt/ielts-speak/.env   # QWEN_APIKEY 必需
```

`/etc/systemd/system/ielts-speak.service`:

```ini
[Unit]
Description=IELTS Speaking Quiz
After=network.target

[Service]
WorkingDirectory=/opt/ielts-speak
ExecStart=/opt/ielts-speak/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now ielts-speak
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `QWEN_APIKEY` | — | 必填,百炼 API Key |
| `IELTS_ADMIN_USER` | — | 必填,管理员用户名 (首次启动自动创建) |
| `IELTS_ADMIN_PASSWORD` | — | 必填,管理员密码 (同名已有用户会被提升并重置密码) |
| `IELTS_DB` | `ielts.db` | SQLite 数据库路径 (用户/会话/抽题历史) |
| `IELTS_SPEAK_TTS_BASEURL` | MaaS 专属域名 | qwen3-tts-flash 端点 |
| `IELTS_SPEAK_TTS_MODEL` | `qwen3-tts-flash` | TTS 模型 |
| `IELTS_SPEAK_TTS_CACHE` | `.cache/tts` | TTS 缓存目录 |
| `IELTS_SPEAK_DATA` | `2605-08-speak.md` | 题库路径 |

## 项目结构

```
main.py          FastAPI 应用 (API + 静态托管)
parser.py        题库 md → JSON (含 PDF 拼接问题清洗)
tts.py           qwen3-tts-flash 合成 + 磁盘缓存
db.py            SQLite 连接与建表 (用户/会话/抽题历史)
auth.py          密码哈希 (PBKDF2-SHA256)、会话、管理员注入
users_api.py     登录/登出/当前用户 (无注册接口)
session_api.py   抽题会话 (避重加权 + 历史记录)
admin_api.py     管理员用户管理端点
sampling.py      纯抽样逻辑 (衰减权重)
static/          前端 (HTML/CSS/JS,无框架)
tests/           pytest (39 个用例)
2605-08-speak.md 题库 (2026 5–8 月)
```

## 账号说明

- 注册关闭:账号全部由管理员在「管理后台」(`/admin.html`,首页登录后可见)创建。
- 所有页面与接口强制登录:未登录访问任意页面跳转 `/login.html?next=...`,接口返回 401。
- 管理员账号由环境变量 `IELTS_ADMIN_USER` / `IELTS_ADMIN_PASSWORD` 注入,仅存于服务器 `.env`,不入库、不进仓库。
- 密码仅存 PBKDF2-SHA256 哈希 (20 万次迭代 + 随机盐),会话为 HttpOnly Cookie,30 天有效。

## 版本记录

| 日期 | 版本 | 更新内容 |
|---|---|---|
| 2026-08-14 | 0.3.0 | 中途暂停续答、避重加权抽样、账号系统 (登录页 + 后台建号 + 强制登录)、右上角账号区 |
| 2026-08-05 | 0.2.0 | 雅思口语随机抽题 (P1/P2/P3)、qwen3-tts-flash 语音提问、考场挂钟 |
| 2026-07-31 | 0.1.0 | 词汇音频播放器:最小 HTTP 服务 + 播放器 UI |

## 说明

- 题库来源为公开备考资料整理,`.env` 含密钥,不入库。
