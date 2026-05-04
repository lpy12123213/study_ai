from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive
from backend.database.repositories.content.study_archives import get_study_archive as db_get_study_archive
from backend.database.repositories.system.learning_plans import create_learning_plan as db_create_learning_plan
from backend.database.repositories.system.learning_plans import get_learning_plan as db_get_learning_plan
from backend.database.repositories.system.learning_plans import list_learning_plans as db_list_learning_plans
from backend.database.repositories.system.learning_plans import (
    set_learning_plan_item_completed as db_set_learning_plan_item_completed,
)

router = APIRouter(prefix="/learning-plans", tags=["learning-plans"], dependencies=[Depends(require_auth)])
logger = get_logger(__name__)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("", response_model=dict)
async def list_plans(
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=50),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    plans = await db_list_learning_plans(user_id=user_id, include_archived=bool(include_archived), limit=limit)
    return {"plans": plans, "count": len(plans)}


@router.get("/{plan_id}", response_model=dict)
async def get_plan(plan_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    plan = await db_get_learning_plan(user_id=user_id, plan_id=int(plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="learning_plan_not_found")
    return {"plan": plan}


@router.post("", response_model=dict)
async def create_plan(payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    title = str(payload.get("title") or "学习计划").strip() or "学习计划"
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []

    items: List[dict] = []
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        due_at = _parse_iso_datetime(raw.get("due_at") or raw.get("dueAt"))
        items.append(
            {
                "title": str(raw.get("title") or "").strip() or f"任务 {idx + 1}",
                "description": str(raw.get("description") or "").strip(),
                "due_at": due_at,
                "completed": bool(raw.get("completed")),
                "sort_order": int(raw.get("sort_order") or idx),
                "source_ref": raw.get("source_ref") if isinstance(raw.get("source_ref"), dict) else {},
            }
        )

    try:
        plan = await db_create_learning_plan(user_id=user_id, title=title, items=items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("create_learning_plan_failed", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="create_learning_plan_failed")

    return {"success": True, "plan": plan}


@router.post("/items/{item_id}/completed", response_model=dict)
async def set_item_completed(item_id: int, payload: Dict[str, Any], user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    completed = bool(payload.get("completed"))
    ok = await db_set_learning_plan_item_completed(user_id=user_id, item_id=int(item_id), completed=completed)
    if not ok:
        raise HTTPException(status_code=404, detail="learning_plan_item_not_found")
    return {"success": True}


@router.post("/from-study-archive/{archive_id}", response_model=dict)
async def create_plan_from_study_archive(
    archive_id: int,
    payload: Optional[Dict[str, Any]] = None,
    user: dict = Depends(require_auth),
) -> dict:
    """Generate a simple todo list from a StudyArchive (read/practice/review)."""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    include_practice = bool(body.get("include_practice", True))
    include_review = bool(body.get("include_review", True))

    archive = await db_get_study_archive(user_id=user_id, archive_id=int(archive_id))
    if not archive:
        raise HTTPException(status_code=404, detail="study_archive_not_found")

    title = str(body.get("title") or f"学习计划：{str(archive.get('topic') or '').strip()}" or "学习计划").strip() or "学习计划"

    sections = archive.get("sections") if isinstance(archive.get("sections"), list) else []
    now = utcnow_naive()

    items: List[dict] = []
    sort = 0
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_title = str(sec.get("title") or "").strip()
        if not sec_title:
            continue
        items.append(
            {
                "title": f"阅读：{sec_title}",
                "description": "阅读本节并做简要笔记（可添加批注）。",
                "due_at": now + timedelta(days=min(30, max(0, sort // 3))),
                "sort_order": sort,
                "source_ref": {"type": "study_archive_section", "archive_id": int(archive_id), "section_id": sec.get("id")},
            }
        )
        sort += 1

    if include_practice:
        items.append(
            {
                "title": "练习：针对知识点做题",
                "description": "优先练习薄弱知识点；可从错题本生成练习卷。",
                "due_at": now + timedelta(days=min(30, max(0, sort // 3))),
                "sort_order": sort,
                "source_ref": {"type": "study_archive", "archive_id": int(archive_id), "hint": "practice"},
            }
        )
        sort += 1

    if include_review:
        items.append(
            {
                "title": "复盘：总结 + 回看错题",
                "description": "整理易错点与疑问；标记未解决问题并加入复习提醒。",
                "due_at": now + timedelta(days=min(30, max(0, sort // 3))),
                "sort_order": sort,
                "source_ref": {"type": "study_archive", "archive_id": int(archive_id), "hint": "review"},
            }
        )

    try:
        plan = await db_create_learning_plan(user_id=user_id, title=title, items=items)
    except Exception:
        logger.exception("create_learning_plan_from_archive_failed", extra={"user_id": user_id, "archive_id": archive_id})
        raise HTTPException(status_code=500, detail="create_learning_plan_failed")

    return {"success": True, "plan": plan}
