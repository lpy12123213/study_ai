from __future__ import annotations

import os
from typing import List, Optional

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import CanvasBoard, CanvasBoardVersion


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


async def create_canvas_board(
    *,
    user_id: str,
    title: str = "",
    subject: str = "",
    snapshot: str = "",
    session: Optional[AsyncSession] = None,
) -> dict:
    title = (title or "").strip() or "新画布"
    subject = (subject or "").strip()
    snapshot = snapshot or ""
    uid = _require_user_id(user_id)

    own = session is None
    if own:
        async with async_session_maker() as session:
            payload = await create_canvas_board(
                user_id=uid, title=title, subject=subject, snapshot=snapshot, session=session
            )
            await session.commit()
            return payload

    board = CanvasBoard(user_id=uid, title=title, subject=subject, snapshot=snapshot, revision=1)
    session.add(board)
    await session.flush()
    await session.refresh(board)
    return {
        "id": board.id,
        "user_id": board.user_id,
        "title": board.title,
        "subject": board.subject,
        "revision": board.revision,
        "created_at": board.created_at.isoformat() if board.created_at else "",
        "updated_at": board.updated_at.isoformat() if board.updated_at else "",
    }


async def list_canvas_boards(
    *,
    user_id: str,
    limit: int = 50,
    query: str = "",
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    limit = max(1, min(int(limit or 50), 200))
    query = (query or "").strip()
    uid = _require_user_id(user_id)

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_canvas_boards(user_id=uid, limit=limit, query=query, session=session)

    stmt = select(CanvasBoard).where(CanvasBoard.user_id == uid).order_by(desc(CanvasBoard.updated_at)).limit(limit)
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(CanvasBoard.title.like(f"%{escaped}%"))
    result = await session.execute(stmt)
    boards = list(result.scalars().all())
    return [
        {
            "id": b.id,
            "user_id": b.user_id,
            "title": b.title,
            "subject": b.subject,
            "revision": b.revision,
            "created_at": b.created_at.isoformat() if b.created_at else "",
            "updated_at": b.updated_at.isoformat() if b.updated_at else "",
        }
        for b in boards
    ]


async def get_canvas_board(
    *,
    user_id: str,
    board_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_canvas_board(user_id=uid, board_id=board_id, session=session)

    result = await session.execute(
        select(CanvasBoard).where(CanvasBoard.id == int(board_id), CanvasBoard.user_id == uid)
    )
    board = result.scalar_one_or_none()
    if not board:
        return None
    return {
        "id": board.id,
        "user_id": board.user_id,
        "title": board.title,
        "subject": board.subject,
        "revision": board.revision,
        "snapshot": board.snapshot or "",
        "created_at": board.created_at.isoformat() if board.created_at else "",
        "updated_at": board.updated_at.isoformat() if board.updated_at else "",
    }


async def update_canvas_board(
    user_id: str,
    board_id: int,
    *,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    snapshot: Optional[str] = None,
    expected_revision: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            payload = await update_canvas_board(
                uid,
                board_id,
                title=title,
                subject=subject,
                snapshot=snapshot,
                expected_revision=expected_revision,
                session=session,
            )
            await session.commit()
            return payload

    result = await session.execute(
        select(CanvasBoard).where(CanvasBoard.id == int(board_id), CanvasBoard.user_id == uid)
    )
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
                "user_id": board.user_id,
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

    await session.flush()
    await session.refresh(board)

    return {
        "success": True,
        "board": {
            "id": board.id,
            "user_id": board.user_id,
            "title": board.title,
            "subject": board.subject,
            "revision": board.revision,
            "snapshot": board.snapshot or "",
            "updated_at": board.updated_at.isoformat() if board.updated_at else "",
        },
    }


async def create_canvas_board_version(
    *,
    user_id: str,
    board_id: int,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            payload = await create_canvas_board_version(user_id=uid, board_id=board_id, session=session)
            await session.commit()
            return payload

    result = await session.execute(
        select(CanvasBoard).where(CanvasBoard.id == int(board_id), CanvasBoard.user_id == uid)
    )
    board = result.scalar_one_or_none()
    if not board:
        return {"success": False, "error": "board_not_found"}

    version = CanvasBoardVersion(board_id=board.id, revision=board.revision, snapshot=board.snapshot or "")
    session.add(version)
    await session.flush()
    await session.refresh(version)

    # Prune history to avoid unbounded DB growth.
    raw_max_keep = str(os.getenv("CANVAS_VERSION_MAX_KEEP") or "").strip()
    try:
        max_keep = int(raw_max_keep) if raw_max_keep else 30
    except ValueError:
        max_keep = 30
    max_keep = max(0, min(max_keep, 500))
    if max_keep > 0:
        old_res = await session.execute(
            select(CanvasBoardVersion.id)
            .where(CanvasBoardVersion.board_id == int(board_id))
            .order_by(desc(CanvasBoardVersion.created_at))
            .offset(max_keep)
            .limit(2000)
        )
        old_ids = [int(x) for x in old_res.scalars().all() if str(x).strip().isdigit()]
        if old_ids:
            await session.execute(delete(CanvasBoardVersion).where(CanvasBoardVersion.id.in_(old_ids)))

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


async def list_canvas_board_versions(
    *,
    user_id: str,
    board_id: int,
    limit: int = 30,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    limit = max(1, min(int(limit or 30), 200))
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_canvas_board_versions(user_id=uid, board_id=board_id, limit=limit, session=session)

    board_result = await session.execute(
        select(CanvasBoard.id).where(CanvasBoard.id == int(board_id), CanvasBoard.user_id == uid)
    )
    if board_result.scalar_one_or_none() is None:
        return []
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


async def get_canvas_board_version(
    *,
    user_id: str,
    board_id: int,
    version_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_canvas_board_version(
                user_id=uid, board_id=board_id, version_id=version_id, session=session
            )

    board_result = await session.execute(
        select(CanvasBoard.id).where(CanvasBoard.id == int(board_id), CanvasBoard.user_id == uid)
    )
    if board_result.scalar_one_or_none() is None:
        return None
    result = await session.execute(
        select(CanvasBoardVersion).where(
            CanvasBoardVersion.board_id == int(board_id), CanvasBoardVersion.id == int(version_id)
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
