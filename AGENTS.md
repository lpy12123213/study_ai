# Repository Guidelines

## Project Structure & Module Organization

- Repo root is the app root.
- `backend/`: FastAPI services (`backend/app.py`) plus agents/crawlers/MCP integrations.
  - `backend/api/`: routers + Pydantic schemas (group by domain).
  - `backend/agent/`, `backend/study_materials/`, `backend/paper_compose/`: AI workflow logic.
  - `backend/database/`: SQLAlchemy models + SQLite helpers.
  - `backend/crawler/`: Playwright scraping utilities.
  - `backend/mcp/`: MCP tools + stdio server entrypoint (`python -m backend.mcp.stdio_server`).
- `frontend/`: Vite + React UI (`frontend/src/`), with `@/` alias for imports.
- `docs/`: architecture/deployment/API docs; `scripts/`: local helpers.
- Local state/output is kept out of git: `.local/`, `data/`, `artifacts/`, `venv/` (see `.gitignore`).

## Build, Test, and Development Commands

Recommended launcher (sets up deps + runs services):

- Windows: `start.bat dev|all|backend|frontend|mcp|setup|doctor`
- Linux/macOS: `./start.sh dev|all|backend|frontend|mcp|setup|doctor`

Manual equivalents:

- Backend API: `python -m uvicorn backend.app:app --reload --port 8000`
- Frontend dev: `cd frontend && npm install && npm run dev`
- Lint/build: `cd frontend && npm run lint` / `npm run build`
- MCP server: `python -m backend.mcp.stdio_server`
- Crawler deps: `python -m playwright install chromium`

## Coding Style & Naming Conventions

- `.editorconfig` is the source of truth (UTF-8, LF, 2 spaces; Python uses 4 spaces).
- Python: prefer type hints and `snake_case`; Ruff is configured in `pyproject.toml` (line length 120).
- Frontend: strict TypeScript (`frontend/tsconfig.json`); components `PascalCase`, hooks `useX`.

## Testing Guidelines

- Backend tests live in `backend/tests/` and use `unittest` (`test_*.py`).
- Run tests: `python -m unittest discover -s backend/tests -p "test_*.py"`
- Smoke check: `start.bat doctor` / `./start.sh doctor` (compile/import + frontend build).

## Commit & Pull Request Guidelines

- Follow Conventional Commits as used in history: `feat(agent): ...`, `fix(mcp): ...`, `refactor: ...`, `docs: ...`, `chore: ...`.
- PRs: describe what/why, include local test steps, add screenshots for UI changes, and update `docs/` when behavior/config changes.

## Security & Configuration Tips

- Copy `.env.example` → `.env`; never commit real keys or scraped content.

- Keep new tools/crawlers rate-limited and respect target site terms.

## Note

- After completing the code, debugging, testing, functional verification, and code REVIEW are required.
- Push to git once after completing a feature.

