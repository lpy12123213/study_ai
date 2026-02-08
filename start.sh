#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")"

CMD="${1:-dev}"

usage() {
  cat <<'EOF'
Usage:
  ./start.sh                 (dev: backend + frontend)
  ./start.sh dev             (backend + frontend)
  ./start.sh all             (backend + frontend + mcp)
  ./start.sh backend         (backend only)
  ./start.sh frontend        (frontend only)
  ./start.sh mcp             (mcp only)
  ./start.sh setup           (install deps only)
  ./start.sh doctor          (run smoke checks)
EOF
}

if [[ "$CMD" == "help" || "$CMD" == "--help" || "$CMD" == "-h" ]]; then
  usage
  exit 0
fi

PYTHON="python3"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python"
fi

ensure_python() {
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "[ERROR] Python not found. Please install Python 3.8+ and retry."
    exit 1
  fi

  if [[ ! -d "venv" ]]; then
    echo "[setup] Creating virtual environment..."
    "$PYTHON" -m venv venv
  fi

  # shellcheck disable=SC1091
  source venv/bin/activate

  echo "[setup] Installing backend deps (if needed)..."
  python -m pip show fastapi >/dev/null 2>&1 || python -m pip install -r requirements.txt
  python -m playwright --version >/dev/null 2>&1 || python -m pip install playwright
  python -m playwright install chromium >/dev/null 2>&1
}

ensure_frontend() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] npm not found. Please install Node.js (LTS) and retry."
    exit 1
  fi
  if [[ ! -d "frontend/node_modules" ]]; then
    echo "[setup] Installing frontend deps..."
    (cd frontend && npm install)
  fi
}

case "$CMD" in
  setup)
    ensure_python
    ensure_frontend
    echo "Setup complete."
    ;;
  doctor)
    ensure_python
    echo "[doctor] python -m compileall . -q"
    python -m compileall . -q
    echo "[doctor] import backend.app, backend.mcp.stdio_server"
    python -c "import backend.app, backend.mcp.stdio_server"
    if command -v npm >/dev/null 2>&1; then
      ensure_frontend
      echo "[doctor] npm run build"
      (cd frontend && npm run build)
    else
      echo "[doctor] npm not found; skip frontend build."
    fi
    echo "Smoke checks passed."
    ;;
  backend)
    ensure_python
    python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
    ;;
  frontend)
    ensure_frontend
    (cd frontend && npm run dev)
    ;;
  mcp)
    ensure_python
    python -m backend.mcp.stdio_server
    ;;
  dev|all)
    ensure_python
    ensure_frontend

    python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload &
    backend_pid=$!

    mcp_pid=""
    if [[ "$CMD" == "all" ]]; then
      python -m backend.mcp.stdio_server &
      mcp_pid=$!
    fi

    cleanup() {
      if [[ -n "${mcp_pid:-}" ]]; then
        kill "$mcp_pid" >/dev/null 2>&1 || true
      fi
      kill "$backend_pid" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT

    (cd frontend && npm run dev)
    ;;
  *)
    echo "[ERROR] Unknown command: $CMD"
    usage
    exit 1
    ;;
esac
