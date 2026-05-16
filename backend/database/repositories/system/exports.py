from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.helpers import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.schema import GeneratedFile, ShareLink


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _hash_password(password: str) -> str:
    raw = str(password or "")
    if not raw:
        return ""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    raw = str(password or "")
    hashed = str(password_hash or "")
    if not hashed:
        return raw == ""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def _row_to_dict(row: ShareLink) -> dict:
    return {
        "token": row.token,
        "user_id": row.user_id,
        "item_type": row.item_type,
        "item_id": row.item_id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "has_password": bool(str(row.password_hash or "").strip()),
    }


async def create_share_link(
    *,
    user_id: str,
    item_type: str,
    item_id: str,
    expires_in_s: Optional[int] = None,
    password: str = "",
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    itype = str(item_type or "").strip()
    iid = str(item_id or "").strip()
    if not itype or not iid:
        raise ValueError("missing_item_ref")

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_share_link(
                user_id=uid,
                item_type=itype,
                item_id=iid,
                expires_in_s=expires_in_s,
                password=password,
                session=session,
            )
            await session.commit()
            return out

    token = secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:48]
    expires_at = None
    if expires_in_s is not None:
        try:
            expires_in_s_int = int(expires_in_s)
        except (TypeError, ValueError):
            expires_in_s_int = 0
        if expires_in_s_int > 0:
            expires_at = utcnow_naive() + timedelta(seconds=expires_in_s_int)

    row = ShareLink(
        token=token,
        user_id=uid,
        item_type=itype,
        item_id=iid,
        expires_at=expires_at,
        password_hash=_hash_password(password),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return _row_to_dict(row)


async def get_share_link(
    *,
    token: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    tok = str(token or "").strip()
    if not tok:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_share_link(token=tok, session=session)

    res = await session.execute(select(ShareLink).where(ShareLink.token == tok))
    row = res.scalar_one_or_none()
    return _row_to_dict(row) if row else None


async def validate_share_link(
    *,
    token: str,
    password: str = "",
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    tok = str(token or "").strip()
    if not tok:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await validate_share_link(token=tok, password=password, session=session)

    res = await session.execute(select(ShareLink).where(ShareLink.token == tok))
    row = res.scalar_one_or_none()
    if not row:
        return None
    if row.expires_at and row.expires_at <= utcnow_naive():
        return None
    if not _verify_password(password, row.password_hash or ""):
        return None
    return _row_to_dict(row)


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
        await session.merge(row)
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
