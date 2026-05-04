from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.paths import resolve_db_path


def _integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA integrity_check;").fetchone()
        return str(row[0] if row else "")
    finally:
        conn.close()


def restore_database(*, backup_path: Path, db_path: Path, yes: bool = False) -> dict:
    source = backup_path.resolve()
    target = db_path.resolve()
    if not source.exists():
        raise FileNotFoundError(f"backup_not_found: {source}")
    if source == target:
        raise ValueError("backup_and_target_are_same_path")
    if _integrity_check(source).lower() != "ok":
        raise RuntimeError("backup_integrity_check_failed")
    if not yes:
        raise RuntimeError("restore_requires_--yes")

    target.parent.mkdir(parents=True, exist_ok=True)
    safety_backup = None
    if target.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        safety_backup = target.with_name(f"{target.stem}.pre-restore-{stamp}{target.suffix}")
        shutil.copy2(target, safety_backup)

    shutil.copy2(source, target)
    if _integrity_check(target).lower() != "ok":
        if safety_backup and safety_backup.exists():
            shutil.copy2(safety_backup, target)
        raise RuntimeError("restored_database_integrity_check_failed")

    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    return {
        "ok": True,
        "source": str(source),
        "target": str(target),
        "safety_backup": str(safety_backup) if safety_backup else "",
        "bytes": int(target.stat().st_size),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a SQLite backup. Stop the backend before running this command."
    )
    parser.add_argument("backup", help="Backup .db file produced by scripts/backup_db.py.")
    parser.add_argument("--db-path", default="", help="Target database path. Defaults to backend database path.")
    parser.add_argument("--yes", action="store_true", help="Required to overwrite the target database.")
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser() if str(args.db_path or "").strip() else resolve_db_path()
    result = restore_database(backup_path=Path(args.backup).expanduser(), db_path=db_path, yes=bool(args.yes))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
