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
