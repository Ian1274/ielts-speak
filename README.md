# IELTS Speaking 随机练习

按真实考试节奏随机抽题练习雅思口语。P1/P3 用 TTS 语音提问 (可重听),P2 显示英文题卡;考前计时用考场挂钟模拟。

两种模式:**练习模式** (自定节奏) 与**全真模拟** (1:1 还原机考视频通话口语,11–14 分钟一口气走完)。

题库:2026 年 5–8 月 (大陆新题 / 大陆老题 / 非大陆新题)。

## 功能

### 练习模式

- **P1 / P2 / P3 三档** tab 切换
- **随机抽题**:先随机选主题 (Music、A tall building you like or dislike…),再在主题下抽指定数量问题;登录用户按 7 天内已抽题避重加权 (抽过越多次,再出现概率越低)
- **中途暂停**:暂停即冻结倒计时并打断语音,继续后从剩余时间接续;若语音未播完被暂停,恢复时重读当前题
- **可配置**:题数 (1–10,默认 2)、停顿 (5–300s,默认 120s)、发音人 (Jennifer / Ethan)、语速 (0.8 / 1.0 / 1.2)
- **P1/P3**:TTS 语音提问 (阿里云 qwen3-tts-flash;实测音色:Jennifer 女声、Ethan 男声,男女分明),🔊 重听按钮;查看题目显示主题 + 英文题目
- **P2**:英文题卡开始即显示,点击「显示主题」才显示英文主题
- **考场挂钟**:指针一圈 = 一题作答时长,最后 10 秒变信号红
- **移动端适配**:操作栏吸底、大按钮、安全区避让
- TTS 磁盘缓存 (`.cache/tts/`),重复文本秒回
- **账号系统**:独立登录页,所有页面和接口强制登录;登录后按人记录抽题历史;管理员在 `/admin.html` 建号、重置密码、查看练习统计

### 全真模拟

- **1:1 还原机考视频通话口语**:顶部导航「练习模式 | 全真模拟」切换,不暂停不打断,总时长 11–14 分钟
- **入场**:考官自我介绍 (Alex)、出示身份证,「第 N 次考试」按已完成场次计数
- **P1**:固定首问 (Work or studies / Hometown)+ 两个随机主题 × 2–3 问,可跳过、可重听
- **P2**:过渡语时英文题卡上屏 (只显正文不显主题,考官画面缩小),1 分钟准备 + 硬倒计时;陈述无倒计时,说完点「继续」
- **P3**:与 P2 同主题 3 问,过渡语后停顿 3 秒
- **结束**:考官致谢 → 时间汇总表 (P1 答题 / P2 答题 / P3 答题)
- **中途退出**:确认后标记弃考,已答题目不记录,也不计入场次
- 考官台词、题卡样式、时间控制均按 IELTS 官方机考流程设计 (见 `docs/mock-exam-flow-design.md`),抽题与练习模式共用 7 天避重加权

## 技术栈

- FastAPI + uvicorn (Python 3.12, uv 管理)
- 原生 HTML/CSS/JS 前端 (无构建)
- TTS:阿里云百炼 qwen3-tts-flash HTTP API (MaaS 业务空间专属域名;实测音色男女分明:Jennifer 女声 / Ethan 男声)
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
| `IELTS_SPEAK_TTS_BASEURL` | MaaS 专属域名 | TTS 端点 |
| `IELTS_SPEAK_TTS_MODEL` | `qwen3-tts-flash` | TTS 模型 |
| `IELTS_SPEAK_TTS_CACHE` | `.cache/tts` | TTS 缓存目录 |
| `IELTS_SPEAK_DATA` | `question_bank/` | 题库目录 |

## 项目结构

```
main.py          FastAPI 应用 (API + 静态托管)
parser.py        题库 md → JSON (question_bank/ 多文件)
tts.py           qwen3-tts-flash 合成 + 磁盘缓存
db.py            SQLite 连接与建表 (用户/会话/抽题历史/模拟场次)
auth.py          密码哈希 (PBKDF2-SHA256)、会话、管理员注入
users_api.py     登录/登出/当前用户 (无注册接口)
session_api.py   抽题会话 (避重加权 + 历史记录)
admin_api.py     管理员用户管理端点
mock_fixed.py    全真模拟考官台词 (固定流程数据)
mock_api.py      全真模拟场次接口 (抽题包 + 结束上报)
sampling.py      纯抽样逻辑 (衰减权重)
static/          前端 (HTML/CSS/JS,无框架;mock.* = 全真模拟)
tests/           pytest (66 个用例)
question_bank/   题库 (2026 5–8 月): mainland|non-mainland × new|old × p1|p2p3 (P3 随 P2 主题存放)
docs/            流程设计、固定题库、实现计划
```

## 账号说明

- 注册关闭:账号全部由管理员在「管理后台」(`/admin.html`,首页登录后可见)创建。
- 所有页面与接口强制登录:未登录访问任意页面跳转 `/login.html?next=...`,接口返回 401。
- 管理员账号由环境变量 `IELTS_ADMIN_USER` / `IELTS_ADMIN_PASSWORD` 注入,仅存于服务器 `.env`,不入库、不进仓库。
- 密码仅存 PBKDF2-SHA256 哈希 (20 万次迭代 + 随机盐),会话为 HttpOnly Cookie,30 天有效。

## 版本记录

| 日期 | 版本 | 更新内容 |
|---|---|---|
| 2026-08-17 | 0.5.0 | 全真模拟体验优化:P2 题卡只显正文、过渡语说完才上屏、倒计时结束即消失、陈述无倒计时、汇总只列 P1/P2/P3 答题、页面内退出确认、倒计时占位行不遮挡、P2 隐藏考生画面、去掉场次/进度计数;题库 P2/P3 主题中译英;修复语音男女混音 (切回 qwen3-tts-flash,男声 Ryan→Ethan);模式导航按钮放大 |
| 2026-08-17 | 0.4.0 | 双模式导航 (练习模式 / 全真模拟);全真模拟 1:1 还原机考:考官台词、P1 固定首问 + 随机主题、P2 题卡 + 硬倒计时、P3 同主题追问、时间汇总;主题重设计为乐观活泼亮色 (阳光橙 × 天空蓝) |
| 2026-08-14 | 0.3.0 | 中途暂停续答、避重加权抽样、账号系统 (登录页 + 后台建号 + 强制登录)、右上角账号区 |
| 2026-08-05 | 0.2.0 | 雅思口语随机抽题 (P1/P2/P3)、qwen3-tts-flash 语音提问、考场挂钟 |
| 2026-07-31 | 0.1.0 | 词汇音频播放器:最小 HTTP 服务 + 播放器 UI |

## 说明

- 题库来源为公开备考资料整理,`.env` 含密钥,不入库。
