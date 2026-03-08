from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, Query

from backend.api.auth import require_auth
from backend.core.settings import settings

router = APIRouter(dependencies=[Depends(require_auth)])

_FIREWORKS_CACHE: Dict[str, Any] = {
    "fetched_at": 0.0,
    "models": None,  # type: ignore[typeddict-item]
}


def _extract_model_ids(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []
    items: Optional[Any] = None
    if isinstance(payload.get("data"), list):
        items = payload.get("data")
    elif isinstance(payload.get("models"), list):
        items = payload.get("models")
    if not isinstance(items, list):
        return []

    out: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        if isinstance(mid, str) and mid.strip():
            out.append(mid.strip())
    # Stable + deterministic ordering for UI
    out = sorted(set(out), key=lambda s: s.lower())
    return out


@router.get("/models/fireworks")
async def list_fireworks_models(force: bool = Query(False)) -> dict:
    """
    List Fireworks models available to the configured API key.

    This endpoint is safe to expose to the frontend because it returns only model IDs
    (no API keys / secrets). Results are cached in-memory for a short TTL.
    """
    if not (settings.fireworks_api_key or "").strip():
        return {"success": False, "provider": "fireworks", "error": "未配置 FIREWORKS_API_KEY"}

    ttl_seconds = 10 * 60
    now = time.time()

    cached_models = _FIREWORKS_CACHE.get("models")
    cached_at = float(_FIREWORKS_CACHE.get("fetched_at") or 0.0)
    if not force and isinstance(cached_models, list) and cached_models and (now - cached_at) < ttl_seconds:
        return {
            "success": True,
            "provider": "fireworks",
            "cached": True,
            "count": len(cached_models),
            "models": cached_models,
        }

    url = f"{(settings.fireworks_base_url or '').rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.fireworks_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            resp = await client.get(url, headers=headers)
    except Exception as exc:
        return {
            "success": False,
            "provider": "fireworks",
            "error": f"请求 Fireworks /models 失败: {str(exc)}",
        }

    if resp.status_code != 200:
        detail = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict) and isinstance(err.get("message"), str):
                    detail = err.get("message") or ""
                elif isinstance(data.get("message"), str):
                    detail = data.get("message") or ""
        except Exception:
            detail = (resp.text or "").strip()

        detail = (detail or "").strip().replace("\n", " ")
        msg = f"Fireworks /models 返回 {resp.status_code}"
        if detail:
            msg = f"{msg} - {detail[:260]}"
        return {"success": False, "provider": "fireworks", "error": msg}

    try:
        payload = resp.json()
    except Exception:
        return {
            "success": False,
            "provider": "fireworks",
            "error": "Fireworks /models 返回非 JSON 响应",
        }

    models = _extract_model_ids(payload)
    _FIREWORKS_CACHE["fetched_at"] = now
    _FIREWORKS_CACHE["models"] = models

    return {
        "success": True,
        "provider": "fireworks",
        "cached": False,
        "count": len(models),
        "models": models,
    }
