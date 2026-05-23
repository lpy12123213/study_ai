from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.engine import async_session_maker, init_db
from backend.database.schema import QuestionCache
from backend.generation.question_library.table_repair import repair_obvious_broken_tables


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair obvious broken table text in question_cache.")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report changes without committing.")
    parser.add_argument("--limit", type=int, default=200, help="Maximum number of question_cache rows to scan.")
    parser.add_argument("--offset", type=int, default=0, help="Offset into question_cache rows.")
    return parser.parse_args()


def _repair_record(row: QuestionCache) -> Dict[str, str]:
    changes: Dict[str, str] = {}
    for field in ("stem", "answer", "analysis"):
        original = str(getattr(row, field) or "")
        repaired = repair_obvious_broken_tables(original)
        if repaired != original:
            changes[field] = repaired
    return changes


async def _run(args: argparse.Namespace) -> int:
    await init_db()

    limit = max(1, int(args.limit or 0))
    offset = max(0, int(args.offset or 0))
    dry_run = bool(args.dry_run)

    stats = {
        "dry_run": dry_run,
        "limit": limit,
        "offset": offset,
        "scanned": 0,
        "changed_rows": 0,
        "changed_fields": 0,
        "sample_question_ids": [],
    }

    async with async_session_maker() as session:
        stmt = select(QuestionCache).order_by(QuestionCache.question_id.asc()).offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows: List[QuestionCache] = list(result.scalars().all())

        for row in rows:
            stats["scanned"] += 1
            changes = _repair_record(row)
            if not changes:
                continue

            stats["changed_rows"] += 1
            stats["changed_fields"] += len(changes)
            if len(stats["sample_question_ids"]) < 12:
                stats["sample_question_ids"].append(str(row.question_id))

            if dry_run:
                continue

            for field, value in changes.items():
                setattr(row, field, value)
            session.add(row)

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
