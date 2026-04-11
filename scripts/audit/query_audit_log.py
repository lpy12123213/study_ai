from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _parse_iso(s: str) -> Optional[float]:
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        # Accept "YYYY-MM-DD", "YYYY-MM-DDTHH:MM:SS", "YYYY-MM-DDTHH:MM:SSZ"
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        if not path.exists():
            return []
    except Exception:
        return []

    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = (line or "").strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:
        return []
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Query .local/audit.jsonl (best-effort).")
    p.add_argument("--path", default="", help="Path to audit.jsonl (default: repo/.local/audit.jsonl)")
    p.add_argument("--user-id", default="", help="Filter by user_id")
    p.add_argument("--action", default="", help="Filter by action (exact match)")
    p.add_argument("--since", default="", help="ISO timestamp, inclusive (e.g. 2026-04-01T00:00:00Z)")
    p.add_argument("--until", default="", help="ISO timestamp, inclusive")
    p.add_argument("--limit", type=int, default=200, help="Max rows to print")
    p.add_argument("--format", choices=["jsonl", "pretty"], default="pretty")
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    path = Path(args.path).expanduser() if str(args.path or "").strip() else (repo_root / ".local" / "audit.jsonl")

    since_ts = _parse_iso(args.since)
    until_ts = _parse_iso(args.until)

    rows = _iter_jsonl(path)
    rows = [r for r in rows if isinstance(r, dict)]

    if args.user_id.strip():
        rows = [r for r in rows if str(r.get("user_id") or "").strip() == str(args.user_id).strip()]
    if args.action.strip():
        rows = [r for r in rows if str(r.get("action") or "").strip() == str(args.action).strip()]

    def _row_ts(r: Dict[str, Any]) -> float:
        t = str(r.get("timestamp") or "").strip()
        ts = _parse_iso(t)
        return float(ts or 0.0)

    if since_ts is not None:
        rows = [r for r in rows if _row_ts(r) >= float(since_ts)]
    if until_ts is not None:
        rows = [r for r in rows if _row_ts(r) <= float(until_ts)]

    rows.sort(key=_row_ts, reverse=True)

    limit = int(args.limit or 0)
    if limit > 0:
        rows = rows[:limit]

    if args.format == "jsonl":
        for r in rows:
            print(json.dumps(r, ensure_ascii=False, default=str))
        return 0

    # pretty
    for r in rows:
        ts = str(r.get("timestamp") or "")
        uid = str(r.get("user_id") or "")
        action = str(r.get("action") or "")
        resource = str(r.get("resource") or "")
        ip = str(r.get("ip") or "")
        print(f"{ts} user_id={uid} action={action} resource={resource} ip={ip}")
        details = r.get("details")
        if isinstance(details, dict) and details:
            try:
                print("  details=" + json.dumps(details, ensure_ascii=False, default=str))
            except Exception:
                print("  details=" + str(details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
