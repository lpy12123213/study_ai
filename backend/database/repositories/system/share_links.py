from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security.password import hash_password as _hash_password
from backend.core.security.password import verify_password as _verify_password
from backend.core.time_utils import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.schema import ShareLink


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


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
