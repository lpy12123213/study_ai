# Repository Guidelines

## Project Structure & Module Organization

- Repo root is the application root.
- `backend/`: FastAPI services (`backend/app.py`) and an OpenAI-compatible adapter (`backend/openai_adapter.py`).
  - `backend/api/`: API routers + Pydantic schemas (grouped by domain).
  - `backend/core/`: shared settings (`backend/core/settings.py`) and subject mappings (`backend/core/subjects.py`).
  - `backend/database/`: SQLAlchemy models + SQLite helpers.
  - `backend/crawler/`: Playwright crawler implementation.
  - `backend/mcp/`: MCP tools + stdio server entrypoint.
- `frontend/`: Vite + React UI (source in `frontend/src/`).
- `docs/`: deployment/integration docs; `scripts/`: local helpers.

## Build, Test, and Development Commands

Backend (dev):

- `pip install -r requirements.txt` (install Python deps)
- `python -m playwright install chromium` (install browser for crawler)
- `python -m uvicorn backend.app:app --reload --port 8000` (run API on `:8000`)

Frontend:

- `cd frontend`
- `npm install` (install JS deps)
- `npm run dev` (UI on `http://localhost:3000`, proxies `/api` → `http://localhost:8000`)
- `npm run lint` / `npm run build`

MCP server:

- `python -m backend.mcp.stdio_server`

## Coding Style & Naming Conventions

- `.editorconfig` is the source of truth: UTF-8, LF, 2-space indent by default; Python uses 4 spaces.
- Python targets 3.8+ (Ruff target `py38` in `pyproject.toml`); prefer type hints and `snake_case`.
- Frontend uses strict TypeScript; React components are `PascalCase` under `frontend/src/`.

## Testing Guidelines

- Backend tests live in `backend/tests/` and use `unittest`.
- Run tests: `python -m unittest discover -s backend/tests`.
- Smoke checks: `python -m compileall . -q` and `python -c "import backend.app, backend.mcp.stdio_server"`.

## Commit & Pull Request Guidelines

- Use Conventional Commits: `feat: ...`, `fix: ...`, `refactor: ...`, `docs: ...`, `chore: ...`.
- PRs should include: what/why, how to test locally, and screenshots for UI changes.
- Never commit secrets or generated artifacts (see `.gitignore`): `.env`, `frontend/dist/`, `frontend/node_modules/`, `*.db`, Playwright user data, `.local/`.

## Security & Configuration Tips

- Use `.env.example` as a template; keep real keys in `.env` (never commit it).
- Prefer shared config/constants in `backend/core/` over duplicating settings in feature code.
