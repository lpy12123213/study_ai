from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "openapi-export-jwt-secret")
os.environ.setdefault("ADMIN_PASSWORD", "openapi-export-admin-password")
os.environ.setdefault("STUDY_AI_DISABLE_AUTH_BOOTSTRAP_WRITE", "1")

from backend.app import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI schema to a JSON file.")
    parser.add_argument("--out", required=True, help="Output path for openapi.json")
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    paths = schema.get("paths")
    if isinstance(paths, dict):
        schema["paths"] = {path: value for path, value in paths.items() if str(path).startswith("/api/")}
    out_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
