from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _build_fts_match(query: str) -> str:
    q = str(query or "").strip()
    if not q:
        return ""

    # Keep it simple and safe: split into basic tokens and AND them.
    # (Avoid passing raw user input to MATCH which can throw on syntax.)
    tokens = re.findall(r"[0-9A-Za-z_]+|[\u4e00-\u9fff]+", q)
    tokens = [t.strip() for t in tokens if t and t.strip()]
    if not tokens:
        tokens = [q]

    safe = []
    for t in tokens[:12]:
        t = t.replace('"', '""')
        safe.append(f'"{t}"')
    return " AND ".join(safe)


async def search_fulltext(
    *,
    user_id: str,
    query: str,
    types: Optional[Sequence[str]] = None,
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    q = str(query or "").strip()
    if not q:
        return []

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await search_fulltext(user_id=uid, query=q, types=types, limit=limit, session=session)

    want = {str(t or "").strip() for t in (types or []) if str(t or "").strip()}
    if not want:
        want = {"conversation", "paper", "study_archive"}

    match = _build_fts_match(q)
    if not match:
        return []

    # Highlight markers (non-printable, unlikely to collide with user text).
    hl_start = "\u0001"
    hl_end = "\u0002"

    results: List[dict] = []

    async def try_query(stmt: str, params: Dict[str, Any]) -> List[dict]:
        try:
            res = await session.execute(text(stmt), params)
            rows = res.mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    if "conversation" in want:
        rows = await try_query(
            """
            SELECT
              'conversation' AS type,
              conversation_id AS conversation_id,
              message_id AS message_id,
              title AS title,
              snippet(messages_fts, 4, :hl_start, :hl_end, '…', 18) AS snippet,
              bm25(messages_fts) AS score
            FROM messages_fts
            WHERE user_id = :user_id AND messages_fts MATCH :match
            ORDER BY score
            LIMIT :limit
            """,
            {"user_id": uid, "match": match, "limit": int(limit or 50), "hl_start": hl_start, "hl_end": hl_end},
        )
        results.extend(rows)

    if "paper" in want:
        rows = await try_query(
            """
            SELECT
              'paper' AS type,
              paper_id AS paper_id,
              question_id AS question_id,
              paper_name AS title,
              snippet(paper_questions_fts, 5, :hl_start, :hl_end, '…', 18) AS snippet,
              bm25(paper_questions_fts) AS score
            FROM paper_questions_fts
            WHERE user_id = :user_id AND paper_questions_fts MATCH :match
            ORDER BY score
            LIMIT :limit
            """,
            {"user_id": uid, "match": match, "limit": int(limit or 50), "hl_start": hl_start, "hl_end": hl_end},
        )
        results.extend(rows)

    if "study_archive" in want:
        rows = await try_query(
            """
            SELECT
              'study_archive' AS type,
              archive_id AS archive_id,
              (subject || ' ' || topic) AS title,
              snippet(study_archives_fts, 5, :hl_start, :hl_end, '…', 18) AS snippet,
              bm25(study_archives_fts) AS score
            FROM study_archives_fts
            WHERE user_id = :user_id AND study_archives_fts MATCH :match
            ORDER BY score
            LIMIT :limit
            """,
            {"user_id": uid, "match": match, "limit": int(limit or 50), "hl_start": hl_start, "hl_end": hl_end},
        )
        results.extend(rows)

    if results:
        # Merge across types by bm25 score (smaller is better).
        def score_key(r: dict) -> float:
            try:
                return float(r.get("score"))
            except (TypeError, ValueError):
                return 1e9

        results.sort(key=score_key)
        return results[: int(limit or 50)]

    # Fallback: if FTS isn't available, try LIKE-based search (best-effort).
    like = f"%{q}%"

    if "conversation" in want:
        rows = await try_query(
            """
            SELECT
              'conversation' AS type,
              m.conversation_id AS conversation_id,
              m.id AS message_id,
              c.title AS title,
              substr(m.content, 1, 260) AS snippet,
              1000000.0 AS score
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = :user_id
              AND m.role <> 'tool'
              AND (m.content LIKE :like OR c.title LIKE :like)
            ORDER BY m.id DESC
            LIMIT :limit
            """,
            {"user_id": uid, "like": like, "limit": int(limit or 50)},
        )
        results.extend(rows)

    if "paper" in want:
        rows = await try_query(
            """
            SELECT
              'paper' AS type,
              pq.paper_id AS paper_id,
              pq.question_id AS question_id,
              p.name AS title,
              substr(COALESCE(pq.knowledge_point,'') || char(10) || COALESCE(pq.stem,''), 1, 260) AS snippet,
              1000000.0 AS score
            FROM paper_questions pq
            JOIN papers p ON p.id = pq.paper_id
            WHERE p.user_id = :user_id
              AND (p.name LIKE :like OR pq.stem LIKE :like OR pq.knowledge_point LIKE :like)
            ORDER BY pq.id DESC
            LIMIT :limit
            """,
            {"user_id": uid, "like": like, "limit": int(limit or 50)},
        )
        results.extend(rows)

    if "study_archive" in want:
        rows = await try_query(
            """
            SELECT
              'study_archive' AS type,
              sa.id AS archive_id,
              (sa.subject || ' ' || sa.topic) AS title,
              substr(COALESCE(sa.topic,'') || char(10) || COALESCE(sa.markdown,''), 1, 260) AS snippet,
              1000000.0 AS score
            FROM study_archives sa
            WHERE sa.user_id = :user_id
              AND (sa.subject LIKE :like OR sa.topic LIKE :like OR sa.markdown LIKE :like)
            ORDER BY sa.id DESC
            LIMIT :limit
            """,
            {"user_id": uid, "like": like, "limit": int(limit or 50)},
        )
        results.extend(rows)

    # Merge across types by bm25 score (smaller is better).
    def score_key(r: dict) -> float:
        try:
            return float(r.get("score"))
        except (TypeError, ValueError):
            return 1e9

    results.sort(key=score_key)
    return results[: int(limit or 50)]
