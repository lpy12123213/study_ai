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
