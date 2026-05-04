from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.config_check import check_config
from backend.core.settings import load_project_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate high-impact Study AI configuration.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when required configuration is missing.")
    args = parser.parse_args()

    load_project_dotenv(override=False)
    result = check_config()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ok={result['ok']} missing={result['counts']['missing']} recommended={result['counts']['recommended']}")
        for group in ("missing", "recommended", "optional"):
            for issue in result.get(group, []):
                print(f"[{group}] {issue['key']}: {issue['message']} -> {issue['action']}")
    return 1 if args.strict and not result["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

