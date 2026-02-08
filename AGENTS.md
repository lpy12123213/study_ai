# Repository Guidelines

## Project Structure & Module Organization

- Repository root is the application root (run commands from repo root unless noted).
- `backend/`: FastAPI services (`backend/app.py`) and OpenAI-compatible adapter (`backend/openai_adapter.py`).
- `backend/api/`: API routers + Pydantic schemas (split by domain: papers/subjects/chat).
- `backend/core/`: shared settings (`backend/core/settings.py`) and subject mappings (`backend/core/subjects.py`). Prefer these over duplicating config/constants.
- `backend/crawler/`: Playwright crawler implementation.
- `backend/database/`: SQLAlchemy models + SQLite helpers.
- `backend/mcp/`: MCP tools + MCP stdio server entrypoint (`python -m backend.mcp.stdio_server`).
- `frontend/`: Vite + React UI.
- `docs/`: deployment and integration docs.

## Build, Test, and Development Commands

Backend (dev):

- `pip install -r requirements.txt`
- `python -m playwright install chromium`
- `python -m uvicorn backend.app:app --reload --port 8000`

Frontend:

- `cd frontend`
- `npm install`
- `npm run dev` (http://localhost:3000, proxies `/api` -> `http://localhost:8000`)
- `npm run lint` / `npm run build`

Convenience scripts: `start.bat` / `start.ps1` / `start.sh`.

## Coding Style & Naming Conventions

- `.editorconfig` is the source of truth: UTF-8, LF, 2-space indent by default; Python uses 4 spaces.
- Python targets 3.8+ (see `pyproject.toml`); use type hints and snake_case modules.
- Frontend uses strict TypeScript; React components are PascalCase and live under `frontend/src/`.

## Testing Guidelines

There is no dedicated test suite in active paths. Before submitting changes, run smoke checks:

- `python -m compileall . -q`
- `python -c "import backend.app, backend.mcp.stdio_server"`
- `cd frontend && npm run build`

## Commit & Pull Request Guidelines

- Follow Conventional Commits (examples from history): `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `chore: ...`.
- PRs should include: what/why, how to test locally, and screenshots for UI changes.
- Never commit secrets (`.env`) or generated artifacts (e.g., `frontend/dist/`, `frontend/node_modules/`, `*.db`, Playwright user data).
