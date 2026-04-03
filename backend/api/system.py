from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from backend.api.auth import require_auth
from backend.api.schemas import SearchHistoryCreate
from backend.core.cache import cache_registry_stats
from backend.core.metrics import generate_metrics, metrics_enabled
from backend.core.settings import settings
from backend.database.engine import engine, pool_metrics
from backend.database.models import add_search_history as db_add_search_history
from backend.database.models import get_user_settings as db_get_user_settings
from backend.database.models import upsert_user_settings as db_upsert_user_settings
from backend.database.repositories.search import search_fulltext as db_search_fulltext

router = APIRouter()


def _disk_check(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(str(path))
        free = int(usage.free)
        total = int(usage.total)
        # Default threshold: 200MB free space.
        min_free = 200 * 1024 * 1024
        ok = free >= min_free
        return {"ok": ok, "path": str(path), "free_bytes": free, "total_bytes": total, "min_free_bytes": min_free}
    except Exception as exc:  # pragma: no cover (best-effort)
        return {"ok": False, "path": str(path), "error": str(exc)}


async def _db_check() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:  # pragma: no cover (best-effort)
        return {"ok": False, "error": str(exc)}


def _llm_config_check() -> dict:
    summary = settings.summary()
    providers = {
        "chat": bool(summary.get("chat_configured")),
        "lesson_plan": bool(summary.get("lesson_plan_configured")),
        "openrouter": bool(summary.get("openrouter_configured")),
        "moonshot": bool(summary.get("moonshot_configured")),
        "fireworks": bool(summary.get("fireworks_configured")),
        "zhipu": bool(summary.get("zhipu_configured")),
        "metaso": bool(summary.get("metaso_configured")),
    }
    any_configured = any(bool(v) for v in providers.values())
    return {"ok": True, "configured": any_configured, "providers": providers, "status": "ok" if any_configured else "warn"}


@router.get("/health/live")
async def health_live() -> dict:
    """Liveness probe (does not check dependencies)."""
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready() -> dict:
    """Readiness probe (checks critical dependencies only)."""
    db = await _db_check()
    disk = _disk_check((Path(__file__).resolve().parents[2] / ".local").resolve())

    ok = bool(db.get("ok")) and bool(disk.get("ok"))
    payload = {
        "status": "ready" if ok else "not_ready",
        "checks": {"db": db, "disk": disk},
    }
    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/health")
async def health_check() -> dict:
    """深度健康检查（best-effort）。"""

    db = await _db_check()
    disk = _disk_check((Path(__file__).resolve().parents[2] / ".local").resolve())
    llm = _llm_config_check()

    ok = bool(db.get("ok")) and bool(disk.get("ok"))
    status = "healthy" if ok else "unhealthy"
    if ok and llm.get("status") == "warn":
        status = "degraded"

    payload = {
        "status": status,
        "service": "exam-paper-assistant",
        "checks": {"db": db, "disk": disk, "llm": llm},
        "db_pool": pool_metrics(),
        "caches": cache_registry_stats(),
    }

    if not ok:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint (authenticated under `/api/metrics`).

    Note: the app also exposes an unauthenticated `/metrics` at the root for
    Prometheus scraping (see `backend.core.metrics.instrument_app`).
    """

    if not metrics_enabled():
        raise HTTPException(status_code=404, detail="metrics_disabled")
    body, content_type = generate_metrics()
    return Response(content=body, media_type=content_type)


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
