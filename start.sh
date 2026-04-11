#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")"

PYTHON="python3"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python"
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[ERROR] python not found in PATH. Please install Python 3.8+ and retry."
  exit 1
fi

exec "$PYTHON" scripts/start.py "${@:-dev}"

