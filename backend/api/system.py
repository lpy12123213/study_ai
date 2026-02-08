from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import SearchHistoryCreate
from backend.core.settings import settings
from backend.database.models import add_search_history as db_add_search_history

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """健康检查"""
    return {"status": "healthy", "service": "exam-paper-assistant"}


@router.get("/config")
async def get_runtime_config() -> dict:
    """返回当前运行配置摘要（不包含密钥等敏感信息）。"""
    return settings.summary()


@router.post("/search-history")
async def record_search_history(data: SearchHistoryCreate) -> dict:
    """记录搜索历史"""
    await db_add_search_history(
      search_type=(data.search_type or "").strip(),
        search_query=(data.search_query or "").strip(),
        result_count=int(data.result_count or 0),
    )
    return {"success": True, "message": "搜索历史已记录"}
