from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import SearchHistory


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


async def add_search_history(
    *,
    user_id: str,
    search_type: str,
    search_query: str,
    result_count: int,
    session: Optional[AsyncSession] = None,
) -> None:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            await add_search_history(
                user_id=uid,
                search_type=search_type,
                search_query=search_query,
                result_count=result_count,
                session=session,
            )
            await session.commit()
        return

    history = SearchHistory(
        user_id=uid,
        search_type=str(search_type or "").strip(),
        search_query=str(search_query or "").strip(),
        result_count=int(result_count or 0),
    )
    session.add(history)
    await session.flush()
