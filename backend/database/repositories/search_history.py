from __future__ import annotations

from backend.database.engine import async_session_maker
from backend.database.schema import SearchHistory


async def add_search_history(*, search_type: str, search_query: str, result_count: int) -> None:
    async with async_session_maker() as session:
        history = SearchHistory(
            search_type=str(search_type or "").strip(),
            search_query=str(search_query or "").strip(),
            result_count=int(result_count or 0),
        )
        session.add(history)
        await session.commit()

