from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.api.schemas import SearchHistoryCreate
from backend.core.settings import settings
from backend.database.models import add_search_history as db_add_search_history
from backend.database.models import get_user_settings as db_get_user_settings
from backend.database.models import upsert_user_settings as db_upsert_user_settings
from backend.database.repositories.search import search_fulltext as db_search_fulltext

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """健康检查"""
    return {"status": "healthy", "service": "exam-paper-assistant"}


@router.get("/config")
async def get_runtime_config(_: dict = Depends(require_auth)) -> dict:
    """返回当前运行配置摘要（不包含密钥等敏感信息）。"""
    return settings.summary()


@router.get("/user-settings")
async def get_user_settings(user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await db_get_user_settings(user_id=user_id)


@router.put("/user-settings")
async def put_user_settings(payload: dict, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    settings_obj = payload.get("settings") if isinstance(payload, dict) else {}
    if settings_obj is None:
        settings_obj = {}
    if not isinstance(settings_obj, dict):
        raise HTTPException(status_code=400, detail="invalid_settings")
    return await db_upsert_user_settings(user_id=user_id, settings=settings_obj)


@router.get("/user-settings/export")
async def export_user_settings(user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await db_get_user_settings(user_id=user_id)


@router.post("/user-settings/import")
async def import_user_settings(payload: dict, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    settings_obj = payload.get("settings") if isinstance(payload, dict) else {}
    if not isinstance(settings_obj, dict):
        raise HTTPException(status_code=400, detail="invalid_settings")
    return await db_upsert_user_settings(user_id=user_id, settings=settings_obj)


@router.post("/search-history")
async def record_search_history(data: SearchHistoryCreate, user: dict = Depends(require_auth)) -> dict:
    """记录搜索历史"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    await db_add_search_history(
        user_id=user_id,
        search_type=(data.search_type or "").strip(),
        search_query=(data.search_query or "").strip(),
        result_count=int(data.result_count or 0),
    )
    return {"success": True, "message": "搜索历史已记录"}


@router.get("/search")
async def search(
    q: str = Query("", min_length=0, max_length=200),
    types: Optional[str] = Query(None, description="comma-separated: conversation,paper,study_archive"),
    limit: int = Query(50, ge=1, le=50),
    user: dict = Depends(require_auth),
) -> dict:
    """Global full-text search (best-effort)."""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    query = str(q or "").strip()
    if not query:
        return {"query": "", "results": [], "count": 0}

    type_list = None
    if isinstance(types, str) and types.strip():
        type_list = [x.strip() for x in types.split(",") if x.strip()]

    results = await db_search_fulltext(user_id=user_id, query=query, types=type_list, limit=int(limit or 50))
    return {"query": query, "results": results, "count": len(results)}
