from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, select

from backend.database.engine import async_session_maker
from backend.database.schema import CanvasBoard, CanvasBoardVersion


async def create_canvas_board(*, title: str = "", subject: str = "", snapshot: str = "") -> dict:
    title = (title or "").strip() or "新画布"
    subject = (subject or "").strip()
    snapshot = snapshot or ""

    async with async_session_maker() as session:
        board = CanvasBoard(title=title, subject=subject, snapshot=snapshot, revision=1)
        session.add(board)
        await session.commit()
        await session.refresh(board)
        return {
            "id": board.id,
            "title": board.title,
            "subject": board.subject,
            "revision": board.revision,
            "created_at": board.created_at.isoformat() if board.created_at else "",
            "updated_at": board.updated_at.isoformat() if board.updated_at else "",
        }


async def list_canvas_boards(*, limit: int = 50, query: str = "") -> List[dict]:
    limit = max(1, min(int(limit or 50), 200))
    query = (query or "").strip()

    async with async_session_maker() as session:
        stmt = select(CanvasBoard).order_by(desc(CanvasBoard.updated_at)).limit(limit)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(CanvasBoard.title.like(f"%{escaped}%"))
        result = await session.execute(stmt)
        boards = list(result.scalars().all())
        return [
            {
                "id": b.id,
                "title": b.title,
                "subject": b.subject,
                "revision": b.revision,
                "created_at": b.created_at.isoformat() if b.created_at else "",
                "updated_at": b.updated_at.isoformat() if b.updated_at else "",
            }
            for b in boards
        ]


async def get_canvas_board(*, board_id: int) -> Optional[dict]:
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return None
        return {
            "id": board.id,
            "title": board.title,
            "subject": board.subject,
            "revision": board.revision,
            "snapshot": board.snapshot or "",
            "created_at": board.created_at.isoformat() if board.created_at else "",
            "updated_at": board.updated_at.isoformat() if board.updated_at else "",
        }


async def update_canvas_board(
    board_id: int,
    *,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    snapshot: Optional[str] = None,
    expected_revision: Optional[int] = None,
) -> dict:
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return {"success": False, "error": "board_not_found"}

        if expected_revision is not None and int(expected_revision) != int(board.revision or 0):
            return {
                "success": False,
                "conflict": True,
                "error": "revision_conflict",
                "server_board": {
                    "id": board.id,
                    "title": board.title,
                    "subject": board.subject,
                    "revision": board.revision,
                    "snapshot": board.snapshot or "",
                    "updated_at": board.updated_at.isoformat() if board.updated_at else "",
                },
            }

        if title is not None:
            board.title = (title or "").strip() or "新画布"
        if subject is not None:
            board.subject = (subject or "").strip()
        if snapshot is not None:
            board.snapshot = snapshot or ""
            board.revision = int(board.revision or 0) + 1

        await session.commit()
        await session.refresh(board)

        return {
            "success": True,
            "board": {
                "id": board.id,
                "title": board.title,
                "subject": board.subject,
                "revision": board.revision,
                "snapshot": board.snapshot or "",
                "updated_at": board.updated_at.isoformat() if board.updated_at else "",
            },
        }


async def create_canvas_board_version(*, board_id: int) -> dict:
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return {"success": False, "error": "board_not_found"}

        version = CanvasBoardVersion(board_id=board.id, revision=board.revision, snapshot=board.snapshot or "")
        session.add(version)
        await session.commit()
        await session.refresh(version)

        latest_result = await session.execute(
            select(CanvasBoardVersion)
            .where(CanvasBoardVersion.board_id == int(board_id))
            .order_by(desc(CanvasBoardVersion.created_at))
            .limit(30)
        )
        versions = list(latest_result.scalars().all())

        return {
            "success": True,
            "version": {
                "id": version.id,
                "board_id": version.board_id,
                "revision": version.revision,
                "created_at": version.created_at.isoformat() if version.created_at else "",
            },
            "versions": [
                {
                    "id": v.id,
                    "board_id": v.board_id,
                    "revision": v.revision,
                    "created_at": v.created_at.isoformat() if v.created_at else "",
                }
                for v in versions
            ],
        }


async def list_canvas_board_versions(*, board_id: int, limit: int = 30) -> List[dict]:
    limit = max(1, min(int(limit or 30), 200))
    async with async_session_maker() as session:
        result = await session.execute(
            select(CanvasBoardVersion)
            .where(CanvasBoardVersion.board_id == int(board_id))
            .order_by(desc(CanvasBoardVersion.created_at))
            .limit(limit)
        )
        versions = list(result.scalars().all())
        return [
            {
                "id": v.id,
                "board_id": v.board_id,
                "revision": v.revision,
                "created_at": v.created_at.isoformat() if v.created_at else "",
            }
            for v in versions
        ]


async def get_canvas_board_version(*, board_id: int, version_id: int) -> Optional[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(CanvasBoardVersion).where(
                CanvasBoardVersion.board_id == int(board_id),
                CanvasBoardVersion.id == int(version_id),
            )
        )
        v = result.scalar_one_or_none()
        if not v:
            return None
        return {
            "id": v.id,
            "board_id": v.board_id,
            "revision": v.revision,
            "snapshot": v.snapshot or "",
            "created_at": v.created_at.isoformat() if v.created_at else "",
        }

