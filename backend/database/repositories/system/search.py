from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging_utils import get_logger
from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id

logger = get_logger(__name__)


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _group_rows(rows: List[dict], *, group_key: str) -> List[dict]:
    """Group 1:N entity rows (conversation/paper) and keep the best row.

    Input rows are expected best-first (bm25 ascending; fallback by id desc).
    Each kept row gains `match_count` (# matching child rows).
    """
    grouped: List[dict] = []
    index: Dict[Any, int] = {}
    for row in rows:
        key = row.get(group_key)
        if key is None:
            continue
        pos = index.get(key)
        if pos is None:
            index[key] = len(grouped)
            row["match_count"] = 1
            grouped.append(row)
        else:
            grouped[pos]["match_count"] = int(grouped[pos].get("match_count") or 0) + 1
    return grouped


def _quota_rows(rows: List[dict], *, group_key: Optional[str], per_type: int) -> List[dict]:
    """Add `match_count` and cap each entity type at `per_type` before cross-type sort."""
    if not rows:
        return rows
    if group_key is None:
        # study_archive / question are 1:1 per entity; no grouping needed.
        for r in rows:
            r["match_count"] = 1
        return rows[:per_type]
    return _group_rows(rows, group_key=group_key)[:per_type]


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
        # Prefix matching preserves type-ahead behavior without falling back to
        # expensive substring scans (for example, 函数 -> 函数单调性).
        safe.append(f'"{t}"*')
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
        want = {"conversation", "paper", "study_archive", "question"}
    limit = int(limit or 50)
    # Per-type quota applied before the cross-type sort so one long conversation
    # or paper cannot crowd out every other result.
    per_type = max(1, math.ceil(limit / max(1, len(want))))

    match = _build_fts_match(q)
    if not match:
        return []

    # Highlight markers (non-printable, unlikely to collide with user text).
    hl_start = "\u0001"
    hl_end = "\u0002"

    results: List[dict] = []

    async def try_query(stmt: str, params: Dict[str, Any], *, entity: str) -> Optional[List[dict]]:
        try:
            res = await session.execute(text(stmt), params)
            rows = res.mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError:
            logger.warning("search_fallback_failed", extra={"entity": entity}, exc_info=True)
            return None

    fts_unavailable: set[str] = set()

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
            {
                "user_id": uid,
                "match": match,
                "limit": limit,
                "hl_start": hl_start,
                "hl_end": hl_end,
            },
            entity="conversation",
        )
        if rows is None:
            fts_unavailable.add("conversation")
        else:
            results.extend(_quota_rows(rows, group_key="conversation_id", per_type=per_type))

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
            {
                "user_id": uid,
                "match": match,
                "limit": limit,
                "hl_start": hl_start,
                "hl_end": hl_end,
            },
            entity="paper",
        )
        if rows is None:
            fts_unavailable.add("paper")
        else:
            results.extend(_quota_rows(rows, group_key="paper_id", per_type=per_type))

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
            {
                "user_id": uid,
                "match": match,
                "limit": limit,
                "hl_start": hl_start,
                "hl_end": hl_end,
            },
            entity="study_archive",
        )
        if rows is None:
            fts_unavailable.add("study_archive")
        else:
            results.extend(_quota_rows(rows, group_key=None, per_type=per_type))

    if "question" in want:
        rows = await try_query(
            """
            SELECT
              'question' AS type,
              question_id AS question_id,
              COALESCE(NULLIF(knowledge_point,''), NULLIF(subject,''), question_id) AS title,
              snippet(question_library_fts, 5, :hl_start, :hl_end, '…', 18) AS snippet,
              bm25(question_library_fts) AS score
            FROM question_library_fts
            WHERE user_id = :user_id
              AND COALESCE(hidden, 0) = 0
              AND question_library_fts MATCH :match
            ORDER BY score
            LIMIT :limit
            """,
            {
                "user_id": uid,
                "match": match,
                "limit": limit,
                "hl_start": hl_start,
                "hl_end": hl_end,
            },
            entity="question",
        )
        if rows is None:
            fts_unavailable.add("question")
        else:
            results.extend(_quota_rows(rows, group_key=None, per_type=per_type))

    if not fts_unavailable:
        # Merge across types by bm25 score (smaller is better).
        def score_key(r: dict) -> float:
            try:
                return float(r.get("score"))
            except (TypeError, ValueError):
                return 1e9

        results.sort(key=score_key)
        return results[:limit]

    # Fall back only for entity types whose FTS query failed. A successful FTS
    # query with zero matches is authoritative and must not trigger table scans.
    want = fts_unavailable
    per_type = max(1, math.ceil(limit / max(1, len(want))))
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
            {"user_id": uid, "like": like, "limit": limit},
            entity="conversation",
        )
        results.extend(_quota_rows(rows or [], group_key="conversation_id", per_type=per_type))

    if "paper" in want:
        rows = await try_query(
            """
            SELECT
              'paper' AS type,
              pq.paper_id AS paper_id,
              pq.question_id AS question_id,
              p.paper_name AS title,
              substr(COALESCE(pq.knowledge_point,'') || char(10) || COALESCE(pq.stem,''), 1, 260) AS snippet,
              1000000.0 AS score
            FROM paper_questions pq
            JOIN papers p ON p.id = pq.paper_id
            WHERE p.user_id = :user_id
              AND (p.paper_name LIKE :like OR pq.stem LIKE :like OR pq.knowledge_point LIKE :like)
            ORDER BY pq.id DESC
            LIMIT :limit
            """,
            {"user_id": uid, "like": like, "limit": limit},
            entity="paper",
        )
        results.extend(_quota_rows(rows or [], group_key="paper_id", per_type=per_type))

    if "question" in want:
        rows = await try_query(
            """
            SELECT
              'question' AS type,
              ql.question_id AS question_id,
              COALESCE(NULLIF(qc.knowledge_point,''), NULLIF(ql.subject,''), ql.question_id) AS title,
              substr(
                COALESCE(qc.stem,'') || char(10) || COALESCE(qc.answer,'') || char(10) || COALESCE(qc.analysis,''),
                1,
                260
              ) AS snippet,
              1000000.0 AS score
            FROM question_library ql
            JOIN question_cache qc ON qc.question_id = ql.question_id
            WHERE ql.user_id = :user_id
              AND COALESCE(ql.hidden, 0) = 0
              AND (
                ql.subject LIKE :like
                OR qc.knowledge_point LIKE :like
                OR qc.stem LIKE :like
                OR qc.answer LIKE :like
                OR qc.analysis LIKE :like
              )
            ORDER BY ql.updated_at DESC
            LIMIT :limit
            """,
            {"user_id": uid, "like": like, "limit": limit},
            entity="question",
        )
        results.extend(_quota_rows(rows or [], group_key=None, per_type=per_type))

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
            {"user_id": uid, "like": like, "limit": limit},
            entity="study_archive",
        )
        results.extend(_quota_rows(rows or [], group_key=None, per_type=per_type))

    # Merge across types by bm25 score (smaller is better).
    def score_key(r: dict) -> float:
        try:
            return float(r.get("score"))
        except (TypeError, ValueError):
            return 1e9

    results.sort(key=score_key)
    return results[:limit]
