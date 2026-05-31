#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

npm run gen:api
node ./scripts/check-generated-api.mjs

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git diff --exit-code -- src/api/__generated__ src/api/__generated__.ts >/dev/null; then
    echo "[gen:api] generated API types changed after generation."
    echo "[gen:api] Review and commit src/api/__generated__/ with the backend schema change."
    git diff -- src/api/__generated__ src/api/__generated__.ts
    exit 1
  fi
fi
