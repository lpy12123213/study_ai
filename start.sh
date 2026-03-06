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

content_fingerprint() {
  if command -v sha256sum >/dev/null 2>&1; then
    for path in "$@"; do
      [[ -f "$path" ]] || continue
      printf '## %s\n' "$path"
      cat "$path"
    done | sha256sum | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    for path in "$@"; do
      [[ -f "$path" ]] || continue
      printf '## %s\n' "$path"
      cat "$path"
    done | shasum -a 256 | awk '{print $1}'
    return
  fi

  "$PYTHON" - "$@" <<'PY'
import hashlib
import pathlib
import sys

parts = []
for raw in sys.argv[1:]:
    path = pathlib.Path(raw)
    if not path.exists():
        continue
    parts.append(f"## {path}\n".encode("utf-8"))
    parts.append(path.read_bytes())
digest = hashlib.sha256(b"".join(parts)).hexdigest()
print(digest)
PY
}

read_stamp() {
  local path="$1"
  if [[ -f "$path" ]]; then
    tr -d '\r\n' <"$path"
  fi
}

write_stamp() {
  local path="$1"
  local value="$2"
  mkdir -p "$(dirname "$path")"
  printf '%s' "$value" >"$path"
}

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

  local backend_stamp="venv/.backend-requirements.sha256"
  local backend_fingerprint
  backend_fingerprint="$(content_fingerprint requirements.txt requirements-dev.txt)"
  if [[ "$(read_stamp "$backend_stamp")" != "$backend_fingerprint" ]]; then
    echo "[setup] Installing backend Python packages..."
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r requirements.txt
    if [[ -f requirements-dev.txt ]]; then
      python -m pip install -r requirements-dev.txt
    fi
    write_stamp "$backend_stamp" "$backend_fingerprint"
  fi

  python -m playwright --version >/dev/null 2>&1 || python -m pip install playwright
  python -m playwright install chromium >/dev/null 2>&1
}

ensure_frontend() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] npm not found. Please install Node.js (LTS) and retry."
    exit 1
  fi
  local frontend_stamp="frontend/node_modules/.deps.sha256"
  local frontend_fingerprint
  frontend_fingerprint="$(content_fingerprint frontend/package.json frontend/package-lock.json)"
  if [[ ! -d "frontend/node_modules" || "$(read_stamp "$frontend_stamp")" != "$frontend_fingerprint" ]]; then
    echo "[setup] Installing frontend deps..."
    (cd frontend && npm install)
    write_stamp "$frontend_stamp" "$frontend_fingerprint"
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
    python -c "import backend.app, backend.mcp.stdio_server, mcp_server.server"
    echo "[doctor] python -m pip check"
    python -m pip check
    echo "[doctor] python -m unittest discover -s backend/tests -p test_*.py"
    python -m unittest discover -s backend/tests -p "test_*.py"
    echo "[doctor] python -m ruff check <maintained backend paths>"
    python -m ruff check \
      backend/api/chat.py \
      backend/api/media.py \
      backend/api/papers.py \
      backend/api/subjects.py \
      backend/api/canvas.py \
      backend/api/study_materials.py \
      backend/chat/llm_mixin.py \
      backend/chat/service.py \
      backend/core/plot_tools.py \
      backend/database/repositories/papers.py \
      backend/study_materials/task_manager.py \
      backend/paper_compose/workflow.py \
      backend/tests
    if command -v npm >/dev/null 2>&1; then
      ensure_frontend
      echo "[doctor] npm run lint"
      (cd frontend && npm run lint)
      echo "[doctor] npm run build"
      (cd frontend && npm run build)
    else
      echo "[doctor] npm not found; skip frontend build."
    fi
    echo "Doctor checks passed."
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
