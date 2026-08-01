# Scripts

`scripts/` 存放项目辅助脚本。脚本必须保持职责单一、默认安全、可从仓库根目录重复运行。主业务入口不应放在本目录。

## 标准入口

优先使用仓库根目录的启动器：

- Windows: `start.bat dev|all|backend|frontend|mcp|setup|doctor`
- Linux / macOS: `./start.sh dev|all|backend|frontend|mcp|setup|doctor`

这些入口最终调用 `scripts/start.py`，它负责创建虚拟环境、安装依赖、启动后端/前端/MCP，以及运行 `doctor` 检查。
`doctor` 会执行结构审计和异常策略预算 gate；当前异常策略预算用于防止遗留 broad-except 数量反弹。GitHub Actions 会复用这些 gate，并额外运行 Alembic 升降级、后端 unittest、前端 lint/build/vitest coverage 和 Playwright smoke。

## 目录分类

- `scripts/audit/`：只读审计、统计、检查脚本。
- `scripts/dev/`：开发辅助和实验脚本，不作为生产入口。
- `scripts/migrate/`：数据、schema 或本地状态迁移脚本。
- `scripts/ops/`：本地运维辅助、状态整理、爬虫相关工具。

常用审计入口：

- `python scripts/audit/structure_lint.py`：检查 API 聚合、领域目录和迁移计划文档。默认只输出 warning；CI 使用 `--strict` 作为 gate。
- `python scripts/audit/exception_policy.py backend --limit 80`：检查裸 `except`、`except Exception` 和静默兜底处理。默认只输出 warning。
- 严格异常策略 gate：`python scripts/audit/exception_policy.py backend --strict --max-total 0 --max-kind pass-only-broad-except=0 --limit 0`，用于阻止异常处理债务反弹。
- `python scripts/audit/lockfile_check.py <lockfile> --platform win|linux`：校验锁文件不包含可编辑/本地路径、已移除工具（mypy）和错误平台 wheel（pywin32 只允许出现在 Windows 锁）。平台可省略，从文件名推断。

## 平台化依赖锁

`setup` 优先安装与当前平台匹配的锁定快照，保证环境可复现：

- `requirements-lock-win.txt`：Windows 快照，`pywin32` 带 `sys_platform == 'win32'` marker。由 `venv/Scripts/python.exe -m pip freeze --exclude-editable` 在 Windows venv 中重新生成。
- `requirements-lock-linux.txt` / `requirements-lock-mac.txt`：分别由 CI（Linux 生成）或本地 venv 生成并提交。
- 回退契约：`scripts/start.py` 的 `_selected_requirement_files` 只选择与当前 `sys.platform` 匹配的锁文件（`win32`→win、`linux`→linux、`darwin`→mac）；匹配锁缺失时回退到 `requirements.txt` 区间解析，绝不安装其他平台的锁。未知平台同样回退到区间解析。
- 校验：提交新锁或升级依赖后运行 `python scripts/audit/lockfile_check.py requirements-lock-win.txt --platform win`（及对应平台的锁）。

## 编写约定

- 运行产物放到 `.local/`、`artifacts/`、`output/` 等忽略目录。
- 破坏性操作必须显式命名、显式确认，并在脚本头部说明影响范围。
- 脚本默认从仓库根目录运行；如果依赖当前工作目录，应在代码中明确解析路径。
- 临时调试脚本不得成为长期入口；稳定能力应迁到后端模块、前端工具或根目录启动器。

## 验收要求

新增或修改脚本时应确认：

- 命令在仓库根目录可运行。
- 默认执行不删除用户数据。
- 输出目录位于忽略路径。
- 如涉及迁移或清理，文档明确输入、输出和回滚方式。
