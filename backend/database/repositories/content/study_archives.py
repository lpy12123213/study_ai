from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging_utils import get_logger
from backend.database.engine import async_session_maker
from backend.database.schema import StudyArchive

logger = get_logger(__name__)


def build_study_archive_fingerprint(*, subject: str, topic: str, requirements: str = "", user_id: str = "") -> str:
    """Deterministic fingerprint for matching "same request" archives.

    Stored as `base_fingerprint` in the DB; the `fingerprint` column is unique per saved version.
    """

    subj = str(subject or "").strip().lower()
    top = str(topic or "").strip().lower()
    req = str(requirements or "").strip().lower()
    uid = str(user_id or "").strip().lower()
    raw = f"{uid}|{subj}|{top}|{req}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _study_archive_version_limit() -> int:
    raw = str(os.getenv("STUDY_ARCHIVE_VERSION_LIMIT") or "").strip()
    if not raw:
        return 20
    try:
        return max(0, min(int(raw), 200))
    except (TypeError, ValueError):
        return 20


def _version_fingerprint(base_fingerprint: str) -> str:
    base = str(base_fingerprint or "").strip().lower()
    seed = uuid.uuid4().hex
    return hashlib.md5(f"{base}|{seed}".encode("utf-8", errors="ignore")).hexdigest()


async def upsert_study_archive(
    *,
    user_id: str,
    subject: str,
    topic: str,
    preset: str,
    requirements: str,
    markdown: str,
    sections: List[Dict[str, Any]],
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    pre = str(preset or "").strip().lower()
    req = str(requirements or "").strip()
    md = str(markdown or "")

    try:
        sections_json = json.dumps(sections or [], ensure_ascii=False)
    except (TypeError, ValueError):
        sections_json = "[]"

    base_fp = build_study_archive_fingerprint(subject=subj, topic=top, requirements=req, user_id=uid)
    fp = _version_fingerprint(base_fp)

    own = session is None
    if own:
        async with async_session_maker() as session:
            payload = await upsert_study_archive(
                user_id=uid,
                subject=subj,
                topic=top,
                preset=pre,
                requirements=req,
                markdown=md,
                sections=sections,
                session=session,
            )
            await session.commit()
            return payload

    row = StudyArchive(
        user_id=uid,
        subject=subj,
        topic=top,
        base_fingerprint=base_fp,
        fingerprint=fp,
        preset=pre,
        requirements=req,
        markdown=md,
        sections_json=sections_json,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    limit = _study_archive_version_limit()
    if limit > 0:
        stale_ids: List[int] = []
        try:
            res = await session.execute(
                select(StudyArchive.id)
                .where(StudyArchive.user_id == uid, StudyArchive.base_fingerprint == base_fp)
                .order_by(desc(StudyArchive.created_at))
                .offset(limit)
            )
            stale_ids = [int(r[0]) for r in res.all() if int(r[0] or 0) > 0]
            if stale_ids:
                await session.execute(delete(StudyArchive).where(StudyArchive.id.in_(stale_ids)))
        except Exception:
            # best-effort retention
            logger.warning(
                "study_archive_retention_cleanup_failed",
                extra={"user_id": uid, "base_fingerprint": base_fp, "stale_count": len(stale_ids)},
                exc_info=True,
            )

    return {"id": row.id, "fingerprint": fp}


async def get_latest_study_archive(
    *,
    user_id: str,
    subject: str,
    topic: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    top = str(topic or "").strip()

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_latest_study_archive(user_id=uid, subject=subj, topic=top, session=session)

    result = await session.execute(
        select(StudyArchive)
        .where(StudyArchive.user_id == uid, StudyArchive.subject == subj, StudyArchive.topic == top)
        .order_by(desc(StudyArchive.created_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    try:
        sections = json.loads(row.sections_json or "[]")
        if not isinstance(sections, list):
            sections = []
    except (TypeError, json.JSONDecodeError):
        sections = []

    return {
        "id": row.id,
        "user_id": row.user_id,
        "subject": row.subject,
        "topic": row.topic,
        "base_fingerprint": getattr(row, "base_fingerprint", "") or "",
        "fingerprint": row.fingerprint,
        "preset": row.preset,
        "requirements": row.requirements,
        "markdown": row.markdown or "",
        "sections": sections,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


async def get_latest_study_archive_for_subject(
    *,
    user_id: str,
    subject: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """Fetch the most recent StudyArchive for a user+subject (ignores topic).

    This is useful when callers pass a free-form "mission" string as `topic`,
    which would never exactly match the stored StudyArchive topic but still
    wants to reuse the user's most recent study materials.
    """

    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_latest_study_archive_for_subject(user_id=uid, subject=subj, session=session)

    result = await session.execute(
        select(StudyArchive)
        .where(StudyArchive.user_id == uid, StudyArchive.subject == subj)
        .order_by(desc(StudyArchive.created_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    try:
        sections = json.loads(row.sections_json or "[]")
        if not isinstance(sections, list):
            sections = []
    except (TypeError, json.JSONDecodeError):
        sections = []

    return {
        "id": row.id,
        "user_id": row.user_id,
        "subject": row.subject,
        "topic": row.topic,
        "base_fingerprint": getattr(row, "base_fingerprint", "") or "",
        "fingerprint": row.fingerprint,
        "preset": row.preset,
        "requirements": row.requirements,
        "markdown": row.markdown or "",
        "sections": sections,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


async def get_study_archive_by_fingerprint(
    *,
    user_id: str,
    subject: str,
    topic: str,
    requirements: str = "",
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """Fetch an archive by deterministic fingerprint (user+subject+topic+requirements).

    This is used as a local knowledge cache to avoid repeated web search for identical requests.
    """

    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    req = str(requirements or "").strip()

    base_fp = build_study_archive_fingerprint(subject=subj, topic=top, requirements=req, user_id=uid)

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_study_archive_by_fingerprint(
                user_id=uid,
                subject=subj,
                topic=top,
                requirements=req,
                session=session,
            )

    result = await session.execute(
        select(StudyArchive)
        .where(StudyArchive.user_id == uid, StudyArchive.base_fingerprint == base_fp)
        .order_by(desc(StudyArchive.created_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        legacy = await session.execute(
            select(StudyArchive)
            .where(StudyArchive.user_id == uid, StudyArchive.fingerprint == base_fp)
            .order_by(desc(StudyArchive.created_at))
            .limit(1)
        )
        row = legacy.scalar_one_or_none()
        if not row:
            return None

    try:
        sections = json.loads(row.sections_json or "[]")
        if not isinstance(sections, list):
            sections = []
    except (TypeError, json.JSONDecodeError):
        sections = []

    return {
        "id": row.id,
        "user_id": row.user_id,
        "subject": row.subject,
        "topic": row.topic,
        "base_fingerprint": getattr(row, "base_fingerprint", "") or "",
        "fingerprint": row.fingerprint,
        "preset": row.preset,
        "requirements": row.requirements,
        "markdown": row.markdown or "",
        "sections": sections,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


async def get_study_archive(
    *,
    user_id: str,
    archive_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    aid = int(archive_id or 0)
    if aid <= 0:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_study_archive(user_id=uid, archive_id=aid, session=session)

    result = await session.execute(
        select(StudyArchive).where(StudyArchive.id == aid, StudyArchive.user_id == uid).limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None

    try:
        sections = json.loads(row.sections_json or "[]")
        if not isinstance(sections, list):
            sections = []
    except (TypeError, json.JSONDecodeError):
        sections = []

    return {
        "id": row.id,
        "user_id": row.user_id,
        "subject": row.subject,
        "topic": row.topic,
        "base_fingerprint": getattr(row, "base_fingerprint", "") or "",
        "fingerprint": row.fingerprint,
        "preset": row.preset,
        "requirements": row.requirements,
        "markdown": row.markdown or "",
        "sections": sections,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


async def list_study_archives(
    *,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_study_archives(user_id=uid, limit=limit, offset=offset, session=session)

    stmt = (
        select(StudyArchive)
        .where(StudyArchive.user_id == uid)
        .order_by(desc(StudyArchive.updated_at))
        .limit(int(limit or 50))
        .offset(int(offset or 0))
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "subject": r.subject,
            "topic": r.topic,
            "base_fingerprint": getattr(r, "base_fingerprint", "") or "",
            "fingerprint": r.fingerprint,
            "preset": r.preset,
            "requirements": r.requirements,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
