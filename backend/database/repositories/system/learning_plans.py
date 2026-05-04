from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.time_utils import utcnow_naive
from backend.database.engine import async_session_maker
from backend.database.schema import LearningPlan, LearningPlanItem


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _json_dumps(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


def _json_loads(value: str, *, default: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _item_to_dict(item: LearningPlanItem) -> dict:
    return {
        "id": int(item.id),
        "title": item.title,
        "description": item.description,
        "due_at": item.due_at.isoformat() if item.due_at else "",
        "completed": bool(int(item.completed or 0)),
        "completed_at": item.completed_at.isoformat() if item.completed_at else "",
        "sort_order": int(item.sort_order or 0),
        "source_ref": _json_loads(item.source_ref_json, default={}),
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def _plan_to_dict(plan: LearningPlan, items: Optional[List[LearningPlanItem]] = None) -> dict:
    return {
        "id": int(plan.id),
        "title": plan.title,
        "archived": bool(int(plan.archived or 0)),
        "created_at": plan.created_at.isoformat() if plan.created_at else "",
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else "",
        "items": [_item_to_dict(i) for i in (items or [])],
    }


async def create_learning_plan(
    *,
    user_id: str,
    title: str,
    items: Optional[List[Dict[str, Any]]] = None,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    title = str(title or "").strip() or "学习计划"
    items = items if isinstance(items, list) else []

    own = session is None
    if own:
        async with async_session_maker() as session:
            out = await create_learning_plan(user_id=uid, title=title, items=items, session=session)
            await session.commit()
            return out

    plan = LearningPlan(user_id=uid, title=title, archived=0)
    session.add(plan)
    await session.flush()
    await session.refresh(plan)

    created_items: List[LearningPlanItem] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        it = LearningPlanItem(
            plan_id=int(plan.id),
            title=str(raw.get("title") or "").strip() or f"任务 {idx + 1}",
            description=str(raw.get("description") or "").strip(),
            due_at=raw.get("due_at") if isinstance(raw.get("due_at"), datetime) else None,
            completed=1 if raw.get("completed") else 0,
            sort_order=int(raw.get("sort_order") or idx),
            source_ref_json=_json_dumps(raw.get("source_ref") or {}, default="{}"),
        )
        session.add(it)
        created_items.append(it)

    await session.flush()
    for it in created_items:
        await session.refresh(it)

    return _plan_to_dict(plan, created_items)


async def list_learning_plans(
    *,
    user_id: str,
    include_archived: bool = False,
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[dict]:
    uid = _require_user_id(user_id)
    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_learning_plans(
                user_id=uid,
                include_archived=include_archived,
                limit=limit,
                session=session,
            )

    stmt = select(LearningPlan).where(LearningPlan.user_id == uid)
    if not include_archived:
        stmt = stmt.where(LearningPlan.archived == 0)
    stmt = stmt.order_by(LearningPlan.updated_at.desc()).limit(int(limit or 50))
    res = await session.execute(stmt)
    plans = res.scalars().all()
    return [_plan_to_dict(p) for p in plans]


async def get_learning_plan(
    *,
    user_id: str,
    plan_id: int,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    pid = int(plan_id or 0)
    if pid <= 0:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_learning_plan(user_id=uid, plan_id=pid, session=session)

    res = await session.execute(select(LearningPlan).where(LearningPlan.id == pid, LearningPlan.user_id == uid))
    plan = res.scalar_one_or_none()
    if not plan:
        return None

    items_res = await session.execute(
        select(LearningPlanItem).where(LearningPlanItem.plan_id == pid).order_by(LearningPlanItem.sort_order.asc())
    )
    items = items_res.scalars().all()
    return _plan_to_dict(plan, items)


async def set_learning_plan_item_completed(
    *,
    user_id: str,
    item_id: int,
    completed: bool,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    iid = int(item_id or 0)
    if iid <= 0:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await set_learning_plan_item_completed(user_id=uid, item_id=iid, completed=completed, session=session)
            await session.commit()
            return ok

    res = await session.execute(
        select(LearningPlanItem, LearningPlan)
        .join(LearningPlan, LearningPlanItem.plan_id == LearningPlan.id)
        .where(LearningPlanItem.id == iid, LearningPlan.user_id == uid)
    )
    row = res.first()
    if not row:
        return False
    item = row[0]
    plan = row[1]

    item.completed = 1 if completed else 0
    item.completed_at = utcnow_naive() if completed else None
    plan.updated_at = utcnow_naive()
    session.add(item)
    session.add(plan)
    await session.flush()
    return True
