from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.record_replay import RecordReplayStore  # noqa: E402


def _read_json(path: Path) -> Dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _default_source() -> Path:
    legacy = REPO_ROOT / ".local" / "llm"
    if legacy.exists():
        return legacy
    return REPO_ROOT / ".local" / "fixtures" / "llm"


def _default_output() -> Path:
    return REPO_ROOT / ".local" / "fixtures" / "llm"


def convert_records(source: Path, output: Path, *, copy_unknown: bool = False) -> Dict[str, Any]:
    store = RecordReplayStore("llm", root=output.parent)
    source = source.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    converted = 0
    copied = 0
    skipped = 0

    for path in sorted(list(source.rglob("*.json"))):
        obj = _read_json(path)
        if not obj:
            skipped += 1
            continue

        request = obj.get("request")
        response = obj.get("response")
        if isinstance(request, dict) and isinstance(response, dict):
            key = store.save(request=request, response=response, meta=obj.get("meta") if isinstance(obj.get("meta"), dict) else {})
            converted += 1
            if path.resolve() != (output / f"{key}.json").resolve() and copy_unknown:
                shutil.copy2(path, output / path.name)
                copied += 1
            continue

        if copy_unknown:
            shutil.copy2(path, output / path.name)
            copied += 1
        else:
            skipped += 1

    return {
        "source": str(source),
        "output": str(output),
        "converted": converted,
        "copied": copied,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert recorded LLM calls into local replay fixtures.")
    parser.add_argument("--source", type=Path, default=_default_source(), help="record source directory")
    parser.add_argument("--output", type=Path, default=_default_output(), help="fixture output directory")
    parser.add_argument("--copy-unknown", action="store_true", help="copy JSON files that are not record/replay payloads")
    args = parser.parse_args()

    summary = convert_records(args.source, args.output, copy_unknown=bool(args.copy_unknown))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
