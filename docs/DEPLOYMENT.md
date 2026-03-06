# Deployment

This document reflects the current repository structure as of March 6, 2026.

## Requirements

- Python 3.10+
- Node.js LTS
- npm
- Playwright Chromium dependencies

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
python -m playwright install chromium
```

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

The FastAPI app initializes the SQLite schema on startup. You do not need to run old `backend/database/models.py` bootstrap commands.

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

## Reverse proxy notes

If you deploy behind Nginx / Caddy / Traefik:

- keep `/api/` routed to FastAPI
- allow streaming for SSE endpoints
- avoid buffering SSE responses
- serve `frontend/dist` assets normally

## Not supported

The old Docker agent worker files were removed because they were dead code and not wired into the app. If you need containerized execution later, reintroduce it as a real feature with tests and documented entrypoints.
