from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from backend.database.engine import async_session_maker
from backend.database.schema import StudyArchive


def build_study_archive_fingerprint(*, subject: str, topic: str, requirements: str = "", user_id: str = "") -> str:
    subj = str(subject or "").strip().lower()
    top = str(topic or "").strip().lower()
    req = str(requirements or "").strip().lower()
    uid = str(user_id or "").strip().lower()
    raw = f"{uid}|{subj}|{top}|{req}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


async def upsert_study_archive(
    *,
    user_id: str,
    subject: str,
    topic: str,
    preset: str,
    requirements: str,
    markdown: str,
    sections: List[Dict[str, Any]],
) -> dict:
    uid = str(user_id or "").strip() or "anonymous"
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    pre = str(preset or "").strip().lower()
    req = str(requirements or "").strip()
    md = str(markdown or "")

    try:
        sections_json = json.dumps(sections or [], ensure_ascii=False)
    except Exception:
        sections_json = "[]"

    fp = build_study_archive_fingerprint(subject=subj, topic=top, requirements=req, user_id=uid)

    async with async_session_maker() as session:
        result = await session.execute(select(StudyArchive).where(StudyArchive.fingerprint == fp))
        existing = result.scalar_one_or_none()
        if existing:
            existing.user_id = uid
            existing.subject = subj
            existing.topic = top
            existing.preset = pre
            existing.requirements = req
            existing.markdown = md
            existing.sections_json = sections_json
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return {"id": existing.id, "fingerprint": fp}

        row = StudyArchive(
            user_id=uid,
            subject=subj,
            topic=top,
            fingerprint=fp,
            preset=pre,
            requirements=req,
            markdown=md,
            sections_json=sections_json,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return {"id": row.id, "fingerprint": fp}


async def get_latest_study_archive(
    *,
    user_id: str,
    subject: str,
    topic: str,
) -> Optional[dict]:
    uid = str(user_id or "").strip() or "anonymous"
    subj = str(subject or "").strip()
    top = str(topic or "").strip()

    async with async_session_maker() as session:
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
        except Exception:
            sections = []

        return {
            "id": row.id,
            "user_id": row.user_id,
            "subject": row.subject,
            "topic": row.topic,
            "fingerprint": row.fingerprint,
            "preset": row.preset,
            "requirements": row.requirements,
            "markdown": row.markdown or "",
            "sections": sections,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }

