# 环境配置

- 包管理：使用 `uv`（非 conda/pip）。运行命令用 `uv run python ...`，安装依赖用 `uv add ...`
- Python 版本：以项目根目录 `.python-version` 文件为准

# 代码规范

- 不可变性：创建新对象，不修改现有对象
- 文件组织：多个小文件优于少数大文件（200-400 行，最多 800 行）
- 错误处理：每层显式处理，快速失败，不静默吞掉错误
- 输入验证：系统边界验证所有输入，不信任外部数据

# 工具

- 网页搜索：优先使用 `grok-search` MCP（`mcp__grok-search__web_search`），不用内置 WebSearch

# 发布流程（每项改动必须执行，顺序不可变）

1. 版本管理：分步提交，每个 commit 单一职责，提交信息带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
2. Mac 本机验证：`uv run pytest` 全绿 + 浏览器（Playwright）验证功能，全部通过才继续
3. GitHub：`git push` 到 `git@github.com:Ian1274/ielts-speak.git`
4. VPS 部署：`sshpass -p '<VPS密码>' ssh -p 10540 root@218.11.5.114` → `/opt/ielts-speak` 下 `git pull && uv sync && systemctl restart ielts-speak`，然后 curl + 浏览器验证外网（http://218.11.5.114:10607/ 与 http://111.62.241.72:10169/）
5. 关键信息不入库：管理员密码等只存服务器 .env；TODO.md 记录已完成项
