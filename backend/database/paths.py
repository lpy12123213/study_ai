from __future__ import annotations

from pathlib import Path


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_db_path() -> Path:
    """Resolve the SQLite DB path used by the backend.

    Preferred: `.local/exam_papers.db`
    Legacy:    `exam_papers.db` at repo root
    """

    project_root = resolve_project_root()
    local_dir = project_root / ".local"
    legacy_db_path = project_root / "exam_papers.db"
    db_path = local_dir / "exam_papers.db"

    try:
        if legacy_db_path.exists() and not db_path.exists():
            local_dir.mkdir(parents=True, exist_ok=True)
            legacy_db_path.replace(db_path)
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path
    except Exception:
        return legacy_db_path
