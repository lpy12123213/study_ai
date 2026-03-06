# Troubleshooting

This guide matches the current codebase layout.

## Backend will not start

Check imports and dependency integrity:

```bash
python -m pip check
python -c "import backend.app, backend.mcp.stdio_server, mcp_server.server"
```

If that fails, rerun setup:

- Windows: `start.bat setup`
- Linux / macOS: `./start.sh setup`

## Frontend will not start

Reinstall frontend packages:

```bash
cd frontend
npm install
npm run lint
npm run build
```

If Vite port `3000` is busy, the Windows launcher automatically picks the next free port. On Linux/macOS you can run `npm run dev -- --port 3001` manually.

## Playwright or crawler issues

Install browser binaries:

```bash
python -m playwright install chromium
```

If Chromium still fails:

- verify system dependencies for Playwright are installed
- rerun `start.bat doctor` or `./start.sh doctor`
- inspect current crawler code under `backend/crawler/zujuan/`

Do not follow old instructions that refer to `crawler/zujuan_crawler.py`; the active code now lives under `backend/crawler/` and `backend/crawler/zujuan/`.

## Subject filters load slowly

First load can initialize Playwright and crawler state.

What to check:

- server logs for crawler startup
- `/api/subjects/{subject}/filters` latency
- whether repeated requests hit the new cache

The app now caches subject filters on both backend and frontend. If you need to clear backend cache during debugging, restart the server.

## Paper detail page looks slow

Paper detail no longer loads AI analysis by default. Use the page-level "Load analysis" action only when needed.

If analysis fails:

- verify external model keys
- verify outbound network access
- retry from the page

## Chat gets slower in long conversations

The backend now trims chat context with both a message-count cap and a character budget.

Relevant environment variables:

- `CHAT_CONTEXT_MAX_MESSAGES`
- `CHAT_CONTEXT_MAX_CHARS`
- `CHAT_CONTEXT_MESSAGE_MAX_CHARS`

If you still see slowdowns, reduce those values further.

## Doctor fails on Ruff

The doctor command intentionally runs Ruff on maintained backend paths, not every historical backend module. If Ruff fails, fix the reported maintained-path issue first before widening the scope.

## Large request rejected

Critical user inputs now have max length limits. Over-limit requests return `400` with a `*_too_long` detail.

Examples:

- `message_too_long`
- `question_too_long`
- `query_too_long`
- `markdown_too_long`

## Media proxy rejects a URL

Expected rejection cases:

- host not on allowlist
- non-image content type
- SVG content
- oversized file

Relevant environment variables:

- `MEDIA_PROXY_ALLOWED_DOMAINS`
- `MEDIA_PROXY_CACHE_TTL_SECONDS`
- `MEDIA_PROXY_CACHE_MAX_BYTES`
- `MEDIA_PROXY_CACHE_MAX_FILES`

## Study-material tasks do not resume

Check:

- `.local/study_materials/tasks/`
- server restarts between task creation and resume
- task TTL settings

Expired snapshots are now deleted on restore, so very old task files will not survive indefinitely.

## MCP client cannot connect

Use the current entrypoint:

```bash
python -m backend.mcp.stdio_server
```

Use the root `mcp_config.json` as a template and replace the placeholder path with an absolute local path.

`mcp_server/server.py` exists only for legacy import compatibility; prefer the backend module entrypoint in new configs.
