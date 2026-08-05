# 雅思口语随机练习 — 任务记录

## 状态:功能完成,待部署验证

### 已完成

- [x] 解析 2605-08-speak.md → JSON (parser.py,含 PDF 拼接问题清洗)
- [x] FastAPI 后端 (main.py):/api/data、/api/voices、/api/tts、/health
- [x] TTS:qwen3-tts-flash (HTTP, MaaS 专属域名),语速调节,磁盘缓存
- [x] 前端 (static/):P1/P2/P3 tab、题数/停顿/发音人/语速配置、TTS 语音提问 + 重听、P2 英文题卡 + 中文主题切换、P1/P3 主题+题目显示、考场挂钟倒计时、响应式 (桌面/手机)
- [x] 题库审计:修复 2 处 "Why and how?" 拆分、5 处单行续句、4 处重复题、语法/全角清理;解析器增加续句识别 (>15 字符 + 自带问号才切分)
- [x] 本地端到端验证 (Playwright, 桌面 + 移动)

### 待办

- [ ] 上传 GitHub 公开仓库
- [ ] VPS 部署 (systemd + uv)
- [ ] 部署后线上验证

## 部署信息

- 仓库: GitHub 公开
- VPS: 218.11.5.114:10540 (root), 工作目录 /opt/ielts-speak
- 端口: 8000
