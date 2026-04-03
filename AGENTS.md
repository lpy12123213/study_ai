# Repository Guidelines

## Project Structure & Module Organization

Repo root is the app root. `backend/` contains the FastAPI service (`backend/app.py`), domain routers in `backend/api/`, workflow logic in `backend/agent/`, `backend/study_materials/`, and `backend/paper_compose/`, database code in `backend/database/`, crawlers in `backend/crawler/`, and MCP tooling in `backend/mcp/`. `frontend/` is a Vite + React app with source under `frontend/src/` and `@/` path aliases. Docs live in `docs/`; helper scripts live in `scripts/`. Keep generated or local-only data in ignored paths such as `.local/`, `data/`, `artifacts/`, and `venv/`.

## Build, Test, and Development Commands

Preferred entrypoints are `start.bat dev|all|backend|frontend|mcp|setup|doctor` on Windows and `./start.sh dev|all|backend|frontend|mcp|setup|doctor` on Linux/macOS. Manual backend start: `python -m uvicorn backend.app:app --reload --port 8000`. Manual frontend start: `cd frontend && npm install && npm run dev`. Frontend quality checks: `cd frontend && npm run lint` and `npm run build`. Start the MCP server with `python -m backend.mcp.stdio_server`.

## Coding Style & Naming Conventions

Follow `.editorconfig`: UTF-8, LF, 2-space indentation by default, 4 spaces for Python. Python code should prefer type hints, `snake_case`, and Ruff rules from `pyproject.toml` with a 120-character line length. Frontend TypeScript is strict; use `PascalCase` for components, `useX` for hooks, and keep imports on the `@/` alias when resolving from `frontend/src/`.

## Testing Guidelines

Backend tests use `unittest` and live in `backend/tests/` with filenames matching `test_*.py`. Run them with `python -m unittest discover -s backend/tests -p "test_*.py"`. Use `start.bat doctor` or `./start.sh doctor` as a smoke check for import, compile, and frontend build health.

## Commit & Pull Request Guidelines

Follow Conventional Commits, as seen in history: `feat(agent): ...`, `refactor(frontend): ...`, `fix(mcp): ...`, `docs: ...`. PRs should explain what changed and why, list local verification steps, include screenshots for UI changes, and update `docs/` when behavior or configuration changes.

## Security & Configuration Tips

Copy `.env.example` to `.env`; never commit real API keys, scraped content, or local database artifacts. Keep crawlers rate-limited and aligned with target-site terms.

## Superpowers 本地覆写
- 轻量任务不进入完整 brainstorming / writing-plans / using-git-worktrees / subagentdriven-development 链路。
- 轻量任务定义：单文件或小范围修改、明确 bug 修复、配置调整、文案修改、小测试补充。
- 轻量任务默认直接分析代码并实现；只有遇到关键不确定性时才提问，且首次最多问 1 个问题。
- 如果项目上下文、AGENTS.md、现有代码已经能回答的问题，不要重复提问。
- 非我明确要求时，不要默认创建 worktree。
- 非我明确要求时，不要默认把 spec / plan 提交到 git。
- 在 Codex 环境中，默认优先使用 executing-plans，而不是 subagent-driven-development。
- 只有在任务明确适合并行、且平台对子代理支持良好时，才使用 subagent-driven-development。
- 需要确认时，优先一次性给出 2 到 3 个可选方案和推荐，不要把确认拆成过多轮。
- 以下操作仍然必须确认：删除文件、大规模重构、修改 git 历史、推送远程、改环境配置、改 CI、数据
库变更。