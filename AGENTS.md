# Repository Guidelines

## Project Structure & Module Organization

Study AI is a local-first FastAPI + React workspace. `backend/app.py` starts the API; backend domains live under `backend/api/`, `backend/generation/`, `backend/tasks/`, `backend/database/`, `backend/integrations/`, `backend/shared/`, and `backend/mcp/`. Backend tests are in `backend/tests/test_*.py`. The frontend is a Vite app under `frontend/src/`; place complex UI in `features/<domain>/`, route assembly in `pages/`, API code in `api/`, and shared utilities in `components/`, `hooks/`, `lib/`, and `stores/`. Documentation lives in `docs/`, helper scripts in `scripts/`, and local/generated data in ignored paths such as `.local/`, `output/`, `artifacts/`, `data/`, and `venv/`.

## Build, Test, and Development Commands

- `start.bat setup`: install Python, Node, and Playwright dependencies on Windows.
- `start.bat dev`: run backend and frontend together; use `start.bat backend`, `frontend`, or `mcp` for one service.
- `start.bat doctor`: run the repo smoke and quality checks.
- `python -m uvicorn backend.app:app --reload --port 8000`: manual backend start.
- `cd frontend && npm run dev`: manual frontend start.
- `cd frontend && npm run gen:api`: regenerate split OpenAPI TypeScript clients after API changes.

## Coding Style & Naming Conventions

Follow `.editorconfig`: UTF-8, LF line endings, spaces, 2-space defaults, and 4 spaces for Python. Python uses Ruff from `pyproject.toml` with a 120-character line length; avoid new broad `except Exception` blocks unless justified with a local `noqa`. Use `snake_case` for Python, `PascalCase` for React components, and `useX` for hooks. Prefer `@/` imports inside `frontend/src/`.

## Testing Guidelines

Backend tests use `unittest`: `python -m unittest discover -s backend/tests -p "test_*.py"`. Frontend tests use Vitest and Playwright: `cd frontend && npm run test`, `npm run test:coverage`, or `npm run e2e`. For small changes, run the focused backend test file or Vitest file plus `git diff --check`; for release-level confidence, run `start.bat doctor`.

## Commit & Pull Request Guidelines

Recent history mostly follows Conventional Commits, for example `feat(backend): ...`, `feat(agent): ...`, `refactor: ...`, and `docs: ...`. Keep commits scoped and describe behavior, not only files. PRs should include a short summary, linked issue or task when available, verification commands, screenshots for UI changes, and documentation/config updates for user-visible behavior.

## Security & Agent Notes

Copy `.env.example` to `.env`, but never commit real keys, cookies, scraped content, local databases, or generated artifacts. In a dirty worktree, inspect status first, edit only the requested scope, and do not overwrite unrelated user or agent changes.
