from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.paths import resolve_db_path, resolve_project_root


def _quote_sqlite_path(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        return str(row[0] if row else "")
    finally:
        conn.close()


def backup_database(*, db_path: Path, output_dir: Path, name: str = "") -> Path:
    source = db_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"database_not_found: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (name or "").strip())
    target_name = f"{safe_name + '-' if safe_name else ''}exam_papers-{stamp}-{os.getpid()}.db"
    target = (output_dir / target_name).resolve()
    counter = 1
    while target.exists():
        target_name = f"{safe_name + '-' if safe_name else ''}exam_papers-{stamp}-{os.getpid()}-{counter}.db"
        target = (output_dir / target_name).resolve()
        counter += 1

    conn = sqlite3.connect(str(source))
    try:
        conn.execute(f"VACUUM INTO {_quote_sqlite_path(target)};")
    finally:
        conn.close()

    if _integrity_check(target).lower() != "ok":
        try:
            target.unlink(missing_ok=True)
        finally:
            raise RuntimeError("backup_integrity_check_failed")
    return target


def main() -> int:
    root = resolve_project_root()
    parser = argparse.ArgumentParser(description="Create a SQLite backup with VACUUM INTO.")
    parser.add_argument("--db-path", default="", help="Source database path. Defaults to backend database path.")
    parser.add_argument("--output-dir", default=str(root / ".local" / "backups" / "db"), help="Backup directory.")
    parser.add_argument("--name", default="", help="Optional filename prefix, e.g. before-upgrade.")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser() if str(args.db_path or "").strip() else resolve_db_path()
    backup_path = backup_database(db_path=db_path, output_dir=Path(args.output_dir).expanduser(), name=args.name)
    print(
        json.dumps(
            {
                "ok": True,
                "source": str(db_path.resolve()),
                "backup": str(backup_path),
                "bytes": int(backup_path.stat().st_size),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
