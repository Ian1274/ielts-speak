# WordPlayer

IELTS 雅思单词听力播放器。粘贴单词列表，浏览器朗读英文。

纯前端 — 单 HTML 文件，零依赖。后端仅一个 Python stdlib HTTP 服务器托管静态文件。

## 功能

- 粘贴单词列表（一行一个），自动过滤中文
- 浏览器 SpeechSynthesis 朗读，支持多语音选择
- 默认英音女声 Flo (en-GB)
- 速度、间隔、重复次数可调
- 随机顺序播放
- 播放进度条 + 状态指示

## 本地运行

```bash
uv run python main.py
# → http://localhost:8127/player.html
```

或者直接浏览器打开 `player.html` 即可使用。

## 部署

VPS 常山1 (Ubuntu 24.04) — systemd 服务：

```bash
systemctl status wordplayer
```

端口映射：
- 联通: `http://218.11.5.114:10057/player.html`
- 移动: `http://111.62.241.102:10687/player.html`

## 文件

| 文件 | 说明 |
|------|------|
| `player.html` | 前端播放器（核心） |
| `main.py` | HTTP 静态文件服务器 |
| `pyproject.toml` | Python 项目配置 |
