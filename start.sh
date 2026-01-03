#!/bin/bash

# Convenience entrypoint from repo root.
# Delegates to the real launcher under `exam_paper_assistant/`.

set -euo pipefail

cd "$(dirname "$0")/exam_paper_assistant"
./start.sh "$@"

