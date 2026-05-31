from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Mapping

from backend.core import business_metrics
from backend.llm.sse_parser import usage_cached_tokens

_DEBUG_LIMIT = 200
_debug_lock = threading.Lock()
_debug_calls: Deque[Dict[str, Any]] = deque(maxlen=_DEBUG_LIMIT)


def _usage_int(usage: Mapping[str, Any] | None, *keys: str) -> int:
    if not isinstance(usage, Mapping):
        return 0
    for key in keys:
        try:
            value = int(usage.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _usage_float(usage: Mapping[str, Any] | None, *keys: str) -> float:
    if not isinstance(usage, Mapping):
        return 0.0
    for key in keys:
        try:
            value = float(usage.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def usage_summary(usage: Mapping[str, Any] | None) -> Dict[str, Any]:
    prompt_tokens = _usage_int(usage, "prompt_tokens", "input_tokens", "promptTokens")
    completion_tokens = _usage_int(usage, "completion_tokens", "output_tokens", "completionTokens")
    total_tokens = _usage_int(usage, "total_tokens", "totalTokens")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    cost_usd = _usage_float(usage, "cost_usd", "estimated_cost_usd", "total_cost_usd", "cost", "estimated_cost")
    cached_tokens = usage_cached_tokens(dict(usage or {}))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": round(cost_usd, 8),
    }


def record_llm_call(
    *,
    provider: str,
    model: str,
    usage: Mapping[str, Any] | None,
    tier: str = "default",
    status: str = "ok",
    mode: str = "live",
    stream: bool = False,
    elapsed_s: float | None = None,
    finish_reason: str = "",
    request_id: str = "",
) -> None:
    business_metrics.record_llm_usage(provider=provider, model=model, usage=usage, tier=tier)

    item = {
        "ts_s": time.time(),
        "provider": str(provider or "unknown"),
        "model": str(model or "unknown"),
        "tier": str(tier or "default"),
        "status": str(status or "unknown"),
        "mode": str(mode or "live"),
        "stream": bool(stream),
        "finish_reason": str(finish_reason or ""),
        "request_id": str(request_id or ""),
        "elapsed_s": None if elapsed_s is None else round(float(elapsed_s), 4),
        "usage": usage_summary(usage),
    }

    with _debug_lock:
        _debug_calls.append(item)


def recent_llm_calls(limit: int = 50) -> Dict[str, Any]:
    try:
        n = max(1, min(int(limit or 50), _DEBUG_LIMIT))
    except (TypeError, ValueError):
        n = 50

    with _debug_lock:
        calls = list(_debug_calls)[-n:]

    totals: Dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cost_usd": 0.0,
    }
    by_model: Dict[str, Dict[str, Any]] = {}
    for call in calls:
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
        model_key = f"{call.get('provider') or 'unknown'}:{call.get('model') or 'unknown'}"
        bucket = by_model.setdefault(
            model_key, {"requests": 0, "total_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0}
        )
        bucket["requests"] += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
            value = int(usage.get(key) or 0)
            totals[key] += value
            if key in {"total_tokens", "cached_tokens"}:
                bucket[key] += value
        cost = float(usage.get("cost_usd") or 0)
        totals["cost_usd"] = round(float(totals["cost_usd"]) + cost, 8)
        bucket["cost_usd"] = round(float(bucket["cost_usd"]) + cost, 8)

    return {
        "limit": n,
        "count": len(calls),
        "totals": totals,
        "by_model": by_model,
        "calls": list(reversed(calls)),
    }


def clear_llm_debug_calls() -> None:
    with _debug_lock:
        _debug_calls.clear()
