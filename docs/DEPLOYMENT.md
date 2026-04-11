# Deployment

This document reflects the current repository structure as of March 6, 2026.

## Requirements

- Python 3.10+
- Node.js LTS
- npm
- Playwright Chromium dependencies
- Recommended for PDF export + static vector diagrams (TikZ/Asymptote):
  - `xelatex`
  - `dvisvgm`
  - `asy`

Notes:
- Windows: install MiKTeX (or TeX Live) and ensure the executables above are on `PATH`.
- Linux: install a TeX distribution that includes XeLaTeX + dvisvgm, plus Asymptote.

## Recommended path

### Windows

```bat
start.bat setup
start.bat doctor
start.bat dev
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh setup
./start.sh doctor
./start.sh dev
```

`setup` installs dependencies using requirement and lockfile fingerprints, so rerunning it is safe after dependency changes.

## Manual deployment flow

### 1. Backend environment

```bash
python -m venv venv
```

Activate:

- Windows: `venv\Scripts\activate`
- Linux / macOS: `source venv/bin/activate`

Install backend packages:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
# Optional: install ChromaDB-backed semantic memory on compatible runtimes.
python -m pip install -r requirements-semantic-memory.txt
python -m playwright install chromium
```

Base setup does not require ChromaDB. If the optional semantic-memory requirements are skipped, the backend uses the
built-in JSONL fallback store instead.

## Frontend API base URL

The frontend uses a single API base setting:

- `VITE_API_BASE_URL` (defaults to `/api`)

Same-origin deploy (recommended): keep the default `/api` and let the backend serve `frontend/dist`.

Cross-origin deploy (frontend hosted separately): set `VITE_API_BASE_URL` to an absolute URL like `https://your-backend.example/api`
and rebuild the frontend.

### 2. Frontend build

```bash
cd frontend
npm install
npm run lint
npm run build
cd ..
```

### 3. Backend start

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

The FastAPI app initializes the SQLite schema on startup (see `backend/database/migrations.py`). No manual bootstrap commands are required.

### 4. MCP server start

```bash
python -m backend.mcp.stdio_server
```

## Health checks

Run the built-in doctor command before shipping:

```bash
start.bat doctor
```

or

```bash
./start.sh doctor
```

This covers imports, backend tests, Ruff on maintained backend paths, `pip check`, frontend lint, and frontend build.

## Data and storage

- SQLite database lives under `.local/`
- Generated media is stored under `.local/media/`
- Study-material task snapshots live under `.local/study_materials/tasks/`

Paper content persistence is opt-in. Default behavior does not persist stem / answer / analysis text unless the corresponding `PAPER_STORE_*` flags are enabled.

## Used question de-dup scope

Paper composition keeps a "used questions" set to avoid repeating question IDs.

By default this is **global** (shared across all users) for backward compatibility.
For multi-user deployments, you likely want **per-user isolation**:

- `USED_QUESTIONS_SCOPE=global` (default) — all users share a single used set
- `USED_QUESTIONS_SCOPE=user` — used set is isolated by `user_id`

Back-compat: `USED_QUESTIONS_PER_USER=1` also enables per-user isolation.

## Reverse proxy notes

If you deploy behind Nginx / Caddy / Traefik:

- keep `/api/` routed to FastAPI
- allow streaming for SSE endpoints
- avoid buffering SSE responses
- serve `frontend/dist` assets normally

### Client IP / rate limiting behind proxies

Rate limiting uses either:
- the access token (preferred), or
- the client IP address (when no token is present).

If you run behind a reverse proxy and want correct client IPs, enable proxy-header parsing **only** for trusted proxy IPs:

- `TRUST_PROXY_HEADERS=1`
- `TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8` (comma-separated IPs/CIDRs; use `*` only if you fully trust your network edge)

If `TRUSTED_PROXIES` is not set, the server does not trust `X-Forwarded-For` / `Forwarded` headers (even when `TRUST_PROXY_HEADERS=1`).

### Request-scoped LLM API key override (security)

The web UI can optionally send per-request model keys via headers (`X-LLM-API-Key` / `X-Moonshot-API-Key`).
This is **disabled by default** for shared deployments.

Controls:
- `LLM_API_KEY_OVERRIDE_ENABLED=1` to allow this feature
- `LLM_API_KEY_OVERRIDE_REQUIRE_ADMIN=1` to restrict it to admin users

When disabled or not permitted, requests that include override headers return `403` with a stable error code
(`llm_api_key_override_disabled` / `llm_api_key_override_forbidden`).

## Pre-commit (optional, recommended)

Install hooks (after backend + frontend dependencies are installed):

```bash
python -m pip install -r requirements-dev.txt
pre-commit install
```

Run checks:

```bash
pre-commit run -a
```

Notes:
- Python hooks use Ruff (`ruff` / `ruff format`).
- Frontend hook runs `npm --prefix frontend run lint` and requires Node + `frontend/node_modules` present.

## Not supported

The old Docker agent worker files were removed because they were dead code and not wired into the app. If you need containerized execution later, reintroduce it as a real feature with tests and documented entrypoints.
