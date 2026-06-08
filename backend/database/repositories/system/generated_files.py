from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time_utils import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.schema import GeneratedFile


def _now_utc() -> datetime:
    return utcnow_naive()


async def upsert_generated_file(
    *,
    filename: str,
    user_id: str,
    file_type: str = "",
    mime_type: str = "",
    sha256: str = "",
    bytes_size: int = 0,
    expires_at: Optional[datetime] = None,
    session: Optional[AsyncSession] = None,
) -> None:
    fn = str(filename or "").strip()
    uid = str(user_id or "").strip()
    if not fn or not uid:
        raise ValueError("missing_filename_or_user_id")

    own = session is None
    if own:
        async with async_session_maker() as session:
            await upsert_generated_file(
                filename=fn,
                user_id=uid,
                file_type=file_type,
                mime_type=mime_type,
                sha256=sha256,
                bytes_size=bytes_size,
                expires_at=expires_at,
                session=session,
            )
            await session.commit()
        return

    existing = await session.get(GeneratedFile, fn)
    if existing is None:
        row = GeneratedFile(
            filename=fn,
            user_id=uid,
            file_type=str(file_type or "").strip(),
            mime_type=str(mime_type or "").strip(),
            sha256=str(sha256 or "").strip(),
            bytes=int(bytes_size or 0),
            created_at=_now_utc(),
            expires_at=expires_at,
        )
        session.add(row)
        return

    existing.user_id = uid
    existing.file_type = str(file_type or "").strip()
    existing.mime_type = str(mime_type or "").strip()
    existing.sha256 = str(sha256 or "").strip()
    existing.bytes = int(bytes_size or 0)
    existing.expires_at = expires_at


async def get_generated_file(*, filename: str, session: Optional[AsyncSession] = None) -> Optional[dict]:
    fn = str(filename or "").strip()
    if not fn:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_generated_file(filename=fn, session=session)

    result = await session.execute(select(GeneratedFile).where(GeneratedFile.filename == fn))
    row = result.scalar_one_or_none()
    if not row:
        return None

    return {
        "filename": str(row.filename or ""),
        "user_id": str(row.user_id or ""),
        "file_type": str(row.file_type or ""),
        "mime_type": str(row.mime_type or ""),
        "sha256": str(row.sha256 or ""),
        "bytes": int(row.bytes or 0),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "expires_at": row.expires_at.isoformat() if row.expires_at else "",
    }


async def list_generated_files(
    *,
    user_id: str,
    file_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Optional[AsyncSession] = None,
) -> list[dict]:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("missing_user_id")

    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, min(int(offset or 0), 100_000))
    ftype = str(file_type or "").strip()

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_generated_files(
                user_id=uid,
                file_type=ftype or None,
                limit=limit,
                offset=offset,
                session=session,
            )

    stmt = select(GeneratedFile).where(GeneratedFile.user_id == uid)
    if ftype:
        stmt = stmt.where(GeneratedFile.file_type == ftype)
    stmt = stmt.order_by(GeneratedFile.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "filename": str(r.filename or ""),
            "user_id": str(r.user_id or ""),
            "file_type": str(r.file_type or ""),
            "mime_type": str(r.mime_type or ""),
            "sha256": str(r.sha256 or ""),
            "bytes": int(r.bytes or 0),
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "expires_at": r.expires_at.isoformat() if r.expires_at else "",
        }
        for r in rows
    ]


async def list_expired_generated_files(
    *,
    limit: int = 200,
    session: Optional[AsyncSession] = None,
) -> list[dict]:
    """List expired generated files (best-effort)."""

    limit = max(1, min(int(limit or 200), 2000))
    now = utcnow_naive()

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_expired_generated_files(limit=limit, session=session)

    stmt = (
        select(GeneratedFile)
        .where(GeneratedFile.expires_at.is_not(None))  # type: ignore[attr-defined]
        .where(GeneratedFile.expires_at <= now)
        .order_by(GeneratedFile.expires_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "filename": str(r.filename or ""),
            "user_id": str(r.user_id or ""),
            "file_type": str(r.file_type or ""),
            "mime_type": str(r.mime_type or ""),
            "sha256": str(r.sha256 or ""),
            "bytes": int(r.bytes or 0),
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "expires_at": r.expires_at.isoformat() if r.expires_at else "",
        }
        for r in rows
    ]


async def delete_generated_file(*, filename: str, session: Optional[AsyncSession] = None) -> bool:
    """Delete the DB row for a generated file (does not delete on-disk bytes)."""

    fn = str(filename or "").strip()
    if not fn:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await delete_generated_file(filename=fn, session=session)
            await session.commit()
            return ok

    existing = await session.get(GeneratedFile, fn)
    if existing is None:
        return False
    try:
        await session.delete(existing)
    except SQLAlchemyError:
        return False
    return True
