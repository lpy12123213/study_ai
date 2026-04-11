"""
Organize local runtime files into `.local/`.

This keeps the project root clean (DB/cache/artifacts/playwright user data are all local-only).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = PROJECT_ROOT / ".local"

LOCAL_DB = LOCAL_DIR / "exam_papers.db"
LOCAL_CACHE_DIR = LOCAL_DIR / "cache"
LOCAL_ARTIFACTS_DIR = LOCAL_DIR / "artifacts"
LOCAL_DATA_DIR = LOCAL_DIR / "data"
LOCAL_PLAYWRIGHT_USER_DIR = LOCAL_DIR / "playwright" / "zujuan_user_data"

LEGACY_DB = PROJECT_ROOT / "exam_papers.db"
LEGACY_CACHE_DIR = PROJECT_ROOT / ".cache"
LEGACY_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
LEGACY_DATA_DIR = PROJECT_ROOT / "data"
LEGACY_PLAYWRIGHT_USER_DIR = PROJECT_ROOT / ".playwright_zujuan_user_data"


def _ensure_dirs() -> None:
    (LOCAL_DIR).mkdir(parents=True, exist_ok=True)
    (LOCAL_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    (LOCAL_ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
    (LOCAL_DATA_DIR).mkdir(parents=True, exist_ok=True)
    (LOCAL_PLAYWRIGHT_USER_DIR.parent).mkdir(parents=True, exist_ok=True)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}__dup{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find unique path for: {path}")


def _move_file(src: Path, dst: Path, *, dry_run: bool) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst = _unique_path(dst)
    if dry_run:
        print(f"[DRY] move file: {src} -> {dst}")
        return
    try:
        src.replace(dst)
    except Exception:
        shutil.move(str(src), str(dst))


def _merge_dir(src_dir: Path, dst_dir: Path, *, dry_run: bool) -> None:
    if not src_dir.exists() or not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in src_dir.iterdir():
        target = dst_dir / child.name
        if target.exists():
            target = _unique_path(target)
        if dry_run:
            print(f"[DRY] move: {child} -> {target}")
            continue
        try:
            child.replace(target)
        except Exception:
            shutil.move(str(child), str(target))

    # Try cleaning up the legacy dir if empty.
    if dry_run:
        return
    try:
        if not any(src_dir.iterdir()):
            src_dir.rmdir()
    except Exception:
        return


def migrate(*, dry_run: bool) -> int:
    _ensure_dirs()

    # 1) DB
    if LEGACY_DB.exists() and not LOCAL_DB.exists():
        try:
            _move_file(LEGACY_DB, LOCAL_DB, dry_run=dry_run)
        except Exception as exc:
            print(f"[WARN] 无法迁移数据库（可能被占用）：{LEGACY_DB}")
            print(f"       错误：{exc}")
            print("       建议：先停止后端（uvicorn）后再重试。")

    # 2) Simple folders (merge contents)
    _merge_dir(LEGACY_CACHE_DIR, LOCAL_CACHE_DIR, dry_run=dry_run)
    _merge_dir(LEGACY_ARTIFACTS_DIR, LOCAL_ARTIFACTS_DIR, dry_run=dry_run)
    _merge_dir(LEGACY_DATA_DIR, LOCAL_DATA_DIR, dry_run=dry_run)

    # 3) Playwright persistent profile (move whole dir if possible)
    if LEGACY_PLAYWRIGHT_USER_DIR.exists() and not LOCAL_PLAYWRIGHT_USER_DIR.exists():
        if dry_run:
            print(f"[DRY] move dir: {LEGACY_PLAYWRIGHT_USER_DIR} -> {LOCAL_PLAYWRIGHT_USER_DIR}")
        else:
            LOCAL_PLAYWRIGHT_USER_DIR.parent.mkdir(parents=True, exist_ok=True)
            try:
                LEGACY_PLAYWRIGHT_USER_DIR.replace(LOCAL_PLAYWRIGHT_USER_DIR)
            except Exception:
                shutil.move(str(LEGACY_PLAYWRIGHT_USER_DIR), str(LOCAL_PLAYWRIGHT_USER_DIR))

    print("[OK] migrate finished")
    print(f"- local dir: {LOCAL_DIR}")
    return 0


def clean(*, yes: bool) -> int:
    if not yes:
        print("[ABORT] clean requires --yes (will delete the whole .local directory).")
        return 2
    if not LOCAL_DIR.exists():
        print("[OK] .local does not exist, nothing to clean.")
        return 0
    shutil.rmtree(LOCAL_DIR, ignore_errors=True)
    print("[OK] removed:", LOCAL_DIR)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_migrate = sub.add_parser("migrate", help="migrate legacy local files into .local/")
    p_migrate.add_argument("--dry-run", action="store_true", help="print planned operations only")

    p_clean = sub.add_parser("clean", help="delete the whole .local directory")
    p_clean.add_argument("--yes", action="store_true", help="confirm deletion")

    args = parser.parse_args(argv)

    if args.cmd == "migrate":
        return migrate(dry_run=bool(args.dry_run))
    if args.cmd == "clean":
        return clean(yes=bool(args.yes))
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
