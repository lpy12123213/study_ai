# Scripts

This directory contains small, task-oriented helper scripts. They are grouped by intent so it's easy to find the right tool quickly.

## Canonical Entrypoint

Use the repo root launchers:

- Windows: `start.bat dev|all|backend|frontend|mcp|setup|doctor`
- macOS/Linux: `./start.sh dev|all|backend|frontend|mcp|setup|doctor`

These wrappers all call `scripts/start.py` (the canonical implementation).

## Categories

- `scripts/audit/`: one-off read-only inspection (logs, metrics, audits).
- `scripts/dev/`: developer helpers and experiments (non-production).
- `scripts/migrate/`: data/schema maintenance and repair utilities.
- `scripts/ops/`: operational scripts (local state organization, crawler helpers, etc.).

## Notes

- Keep runtime outputs under `.local/` or `artifacts/` (not under `backend/` or `frontend/`).
- Scripts should be safe by default; anything destructive should be explicit and well-documented.

