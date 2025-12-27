# Repository Guidelines

## Project Structure & Module Organization

- `exam_paper_assistant/` is the application root (run commands from here unless noted).
- `exam_paper_assistant/backend/`: FastAPI services (`backend/app.py`) and OpenAI-compatible adapter (`backend/openai_adapter.py`).
- `exam_paper_assistant/backend/api/`: API routers + Pydantic schemas (split by domain: papers/subjects/chat).
- `exam_paper_assistant/core/`: shared settings (`core/settings.py`) and subject mappings (`core/subjects.py`). Prefer these over duplicating config/constants.
- `exam_paper_assistant/crawler/`: Playwright crawler implementation.
- `exam_paper_assistant/database/`: SQLAlchemy models + SQLite helpers.
- `exam_paper_assistant/mcp_server/`: MCP server entrypoint (`python -m mcp_server.server`).
- `exam_paper_assistant/frontend/`: Vite + React UI.
- `exam_paper_assistant/docs/`: deployment and integration docs.

## Build, Test, and Development Commands

Backend (dev):

- `cd exam_paper_assistant`
- `pip install -r requirements.txt`
- `python -m playwright install chromium`
- `python -m uvicorn backend.app:app --reload --port 8000`

Frontend:

- `cd exam_paper_assistant/frontend`
- `npm install`
- `npm run dev` (http://localhost:3000, proxies `/api` → `http://localhost:8000`)
- `npm run lint` / `npm run build`

Convenience scripts (Windows): `exam_paper_assistant/start.bat`, `start_backend.bat`, `start_frontend.bat`, `start_mcp.bat`.

## Coding Style & Naming Conventions

- `.editorconfig` is the source of truth: UTF-8, LF, 2-space indent by default; Python uses 4 spaces.
- Python targets 3.8+ (see `pyproject.toml`); use type hints and snake_case modules.
- Frontend uses strict TypeScript; React components are PascalCase and live under `frontend/src/`.

## Testing Guidelines

There is no dedicated test suite in active paths. Before submitting changes, run smoke checks:

- `python -m compileall exam_paper_assistant -q`
- `cd exam_paper_assistant && python -c "import backend.app, mcp_server.server"`
- `cd exam_paper_assistant/frontend && npm run build`

## Commit & Pull Request Guidelines

- Follow Conventional Commits (examples from history): `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `chore: ...`.
- PRs should include: what/why, how to test locally, and screenshots for UI changes.
- Never commit secrets (`.env`) or generated artifacts (e.g., `frontend/dist/`, `frontend/node_modules/`, `*.db`, Playwright user data).

