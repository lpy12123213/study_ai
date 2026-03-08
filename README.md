# Study AI

AI-assisted study and exam-paper workspace built with FastAPI and React.

## What it does

- Chat-based question search and paper creation
- Blueprint-based paper composition
- Study-material generation with resumable SSE tasks
- DeepThink problem solving UI
- Paper management and export
- MCP stdio server for external MCP clients

## Project layout

```text
study_ai/
|-- backend/
|   |-- api/
|   |-- agent/
|   |-- crawler/
|   |-- database/
|   |-- mcp/
|   `-- app.py
|-- frontend/
|   `-- src/
|-- docs/
|-- scripts/
|-- start.bat
|-- start.ps1
|-- start.sh
|-- requirements.txt
|-- requirements-dev.txt
`-- mcp_config.json
```

## Quick start

### Windows

```bat
start.bat setup
start.bat dev
```

Other useful commands:

```bat
start.bat backend
start.bat frontend
start.bat all
start.bat doctor
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh setup
./start.sh dev
```

Other useful commands:

```bash
./start.sh backend
./start.sh frontend
./start.sh all
./start.sh doctor
```

## Manual start

```bash
python -m venv venv
```

Activate the virtualenv:

- Windows: `venv\Scripts\activate`
- Linux / macOS: `source venv/bin/activate`

Install backend dependencies and Playwright:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Start the backend:

```bash
python -m uvicorn backend.app:app --reload --port 8000
```

Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Frontend API base URL

The frontend uses a single API base setting:

- `VITE_API_BASE_URL` (defaults to `/api`)

Same-origin deploy (recommended): keep the default `/api` and let the backend serve `frontend/dist`.

Cross-origin deploy (frontend hosted separately): set `VITE_API_BASE_URL` to an absolute URL like `https://your-backend.example/api`
and rebuild the frontend.

See `docs/DEPLOYMENT.md` for more deployment notes.

Start the MCP server:

```bash
python -m backend.mcp.stdio_server
```

## LLM configuration

By default the backend reads provider/model settings from `.env`. For local development you can also place a
local-only JSON config at `config/model.json` (gitignored) to manage multiple OpenAI-compatible providers and
select an active one.

1. Copy `config/model.example.json` to `config/model.json`
2. Fill `providers.<name>.base_url` and `providers.<name>.api_key`
3. Set `active_provider` and adjust `models` / `params` as needed

Optional: set `MODEL_CONFIG_PATH` to load the config from a custom path.

## Doctor

`start.bat doctor` and `./start.sh doctor` now run:

- `python -m compileall . -q`
- `python -c "import backend.app, backend.mcp.stdio_server, mcp_server.server"`
- `python -m pip check`
- `python -m unittest discover -s backend/tests -p "test_*.py"`
- `python -m ruff check` on maintained backend paths
- `cd frontend && npm run lint`
- `cd frontend && npm run build`

## Configuration

Copy `.env.example` to `.env` and fill in the keys you need.

Common variables:

- `CHAT_PROVIDER`
- `FIREWORKS_API_KEY`
- `OPENROUTER_API_KEY`
- `MAIN_MODEL`
- `SUB_MODEL`
- `DEFAULT_SUBJECT`
- `JWT_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

### Compliance and storage

Default paper persistence is metadata-first:

- By default the app stores paper IDs and lightweight metadata.
- Question stem / answer / analysis content is not persisted unless you opt in.

Available flags:

- `PAPER_STORE_CONTENT=1`
- `PAPER_STORE_STEM=1`
- `PAPER_STORE_ANSWER=1`
- `PAPER_STORE_ANALYSIS=1`

If you need local review content, enable only the minimum flags required for your environment.

## MCP

Preferred entrypoint:

```bash
python -m backend.mcp.stdio_server
```

Template config:

- Root file: `mcp_config.json`

Example path entry:

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "python",
      "args": ["C:/path/to/study_ai/backend/mcp/stdio_server.py"]
    }
  }
}
```

`mcp_server/server.py` is kept only as a legacy import-compatible shim.

## Notes

- The media proxy only allows whitelisted image content types.
- Remote SVG proxying is blocked for security reasons.
- Paper detail pages do not fetch AI analysis by default; analysis is loaded on demand.
- Subject filters are cached server-side and client-side to reduce first-load latency.

## Architecture

See `docs/ARCHITECTURE.md` for module and router indexing.

## Docs

- `docs/DEPLOYMENT.md`
- `docs/TROUBLESHOOTING.md`
- `docs/SVG_TO_LATEX.md`
- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `docs/CHERRY_STUDIO_MCP_GUIDE.md`
