# Repository Guidelines

## Project Structure & Module Organization

Study AI is a local-first FastAPI backend plus a clean-room rewritten frontend. `backend/app.py` starts the API; backend domains live under `backend/api/`, `backend/generation/`, `backend/tasks/`, `backend/database/`, `backend/integrations/`, `backend/shared/`, and `backend/mcp/`. Backend tests are in `backend/tests/test_*.py`. The frontend lives in `frontend/` (Vite 6 + React 18 + TypeScript strict; Tailwind CSS v4 + Radix primitives; React Router v7; TanStack Query v5 for server state; Zustand v5 for client/streaming state): `src/shared/api/` holds the typed `apiFetch` HTTP client and API types, `src/features/*/api.ts` the per-domain endpoint modules, `src/shared/streaming/task-coordinator.ts` the unified SSE/task watch layer, `src/stores/` the auth/ui/tasks stores, `src/components/ui/` the design-system primitives, `src/components/layout/` the app shell, and `src/pages/` plus `src/features/` the route views wired in `src/router.tsx` (route catalog in `src/app/router/`). Documentation lives in `docs/`, helper scripts in `scripts/`, and local/generated data in ignored paths such as `.local/`, `output/`, `artifacts/`, `data/`, and `venv/`.

## Build, Test, and Development Commands

- `start.bat setup`: install the repository dependencies on the current platform, preferring the matching per-platform lock file `requirements-lock-<platform>.txt` (`requirements-lock-win.txt` on Windows, `requirements-lock-linux.txt` on Linux/macOS) when present; deleting the lock file (or its absence) resolves fresh ranges from `requirements.txt`.
- `start.bat doctor`: run the repo smoke and quality checks.
- `python -m uvicorn backend.app:app --reload --port 8000`: manual backend start.
- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev`: Vite dev server on port 5173 (proxies `/api`, including ws, to 8000).
- `cd frontend && npm run build`: typecheck (`tsc -b`) and bundle to `frontend/dist` (served by FastAPI).
- `cd frontend && npm run lint`: ESLint over the frontend sources.
- `python -m backend.evals.study_materials.runner --case all --dry-run`: validate the study-materials benchmark cases; run the benchmark against a live backend with `--case <id|all> --base-url http://127.0.0.1:8000` (see `docs/STUDY_MATERIALS_BENCHMARK.md`).

## Coding Style & Naming Conventions

Follow `.editorconfig`: UTF-8, LF line endings, spaces, 2-space defaults, and 4 spaces for Python. Python uses Ruff from `pyproject.toml` with a 120-character line length; avoid new broad `except Exception` blocks unless justified with a local `noqa`. Use `snake_case` for Python.

## Testing Guidelines

Backend tests use `unittest`: `python -m unittest discover -s backend/tests -p "test_*.py"`. For small changes, run the focused backend test file plus `git diff --check`; for release-level confidence, run `start.bat doctor`. Python lint covers the full tree: `python -m ruff check backend scripts`. Frontend unit tests use Vitest (`cd frontend && npm run test`); visual e2e uses Playwright (`npm run test:e2e`, Windows `*-win32.png` snapshots — run on Windows); also verify the frontend with `npm run build` (includes `tsc`) and `npm run lint`.

## Commit & Pull Request Guidelines

Recent history mostly follows Conventional Commits, for example `feat(backend): ...`, `feat(agent): ...`, `refactor: ...`, and `docs: ...`. Keep commits scoped and describe behavior, not only files. PRs should include a short summary, linked issue or task when available, verification commands, screenshots for UI changes, and documentation/config updates for user-visible behavior.

## Security & Agent Notes

Copy `.env.example` to `.env`, but never commit real keys, cookies, scraped content, local databases, or generated artifacts. In a dirty worktree, inspect status first, edit only the requested scope, and do not overwrite unrelated user or agent changes.

## Frontend Rewrite Boundary

The former `frontend/` tree was intentionally deleted for a clean-room rewrite. Do not restore, inspect, or derive from any historical frontend source, Git blob, commit, diff, build artifact, cache, screenshot, or generated bundle. In particular, do not use `git restore`, `git checkout`, `git show`, or equivalent history-reading commands on the former frontend paths.

Any new frontend must be designed and implemented from a blank directory using only current user requirements, current backend contracts, and non-frontend documentation. Do not aim for layout, component, navigation, interaction-flow, or implementation similarity with the deleted frontend. Restoring or viewing the old frontend requires a new explicit user instruction that overrides this boundary.
