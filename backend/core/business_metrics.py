from __future__ import annotations

import os
from typing import Any, Mapping

from backend.core.logging_utils import get_logger

_LLM_TOKENS = None
_LLM_COST_USD = None
_LLM_REQUESTS = None
_TOOL_CALLS = None
_TASK_TERMINALS = None
_METRICS_READY = False
_METRICS_DISABLED = False
logger = get_logger(__name__)


def _label(value: Any, *, max_chars: int = 100) -> str:
    raw = str(value or "").strip() or "unknown"
    return raw[:max_chars]


def _metrics_enabled() -> bool:
    raw = str(os.getenv("PROMETHEUS_METRICS_ENABLED") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ensure_metrics() -> bool:
    global _LLM_TOKENS, _LLM_COST_USD, _LLM_REQUESTS, _TOOL_CALLS, _TASK_TERMINALS
    global _METRICS_READY, _METRICS_DISABLED

    if _METRICS_READY:
        return True
    if _METRICS_DISABLED or not _metrics_enabled():
        return False

    try:
        from prometheus_client import Counter  # type: ignore

        _LLM_TOKENS = Counter(
            "study_ai_llm_tokens_total",
            "LLM tokens reported by providers.",
            ["provider", "model", "tier"],
        )
        _LLM_COST_USD = Counter(
            "study_ai_llm_cost_usd_total",
            "LLM cost reported by providers in USD.",
            ["provider", "model", "tier"],
        )
        _LLM_REQUESTS = Counter(
            "study_ai_llm_requests_total",
            "LLM requests completed by provider/model.",
            ["provider", "model", "tier", "status"],
        )
        _TOOL_CALLS = Counter(
            "study_ai_tool_calls_total",
            "Agent tool calls by tool name and status.",
            ["name", "status"],
        )
        _TASK_TERMINALS = Counter(
            "study_ai_tasks_terminal_total",
            "Unified tasks that reached a terminal status.",
            ["task_type", "status"],
        )
        _METRICS_READY = True
        return True
    except Exception:
        logger.warning("business_metrics_init_failed", exc_info=True)
        _METRICS_DISABLED = True
        return False


def _usage_total_tokens(usage: Mapping[str, Any] | None) -> int:
    if not isinstance(usage, Mapping):
        return 0
    for key in ("total_tokens", "totalTokens"):
        try:
            value = int(usage.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    total = 0
    for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
        try:
            total += max(0, int(usage.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return total


def _usage_cost_usd(usage: Mapping[str, Any] | None) -> float:
    if not isinstance(usage, Mapping):
        return 0.0
    for key in ("cost_usd", "estimated_cost_usd", "total_cost_usd", "cost", "estimated_cost"):
        try:
            value = float(usage.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def record_llm_usage(*, provider: str, model: str, usage: Mapping[str, Any] | None, tier: str = "default") -> None:
    if not _ensure_metrics():
        return
    try:
        labels = (_label(provider, max_chars=60), _label(model, max_chars=120), _label(tier, max_chars=50))
        _LLM_REQUESTS.labels(*labels, "ok").inc()
        tokens = _usage_total_tokens(usage)
        if tokens > 0:
            _LLM_TOKENS.labels(*labels).inc(tokens)
        cost = _usage_cost_usd(usage)
        if cost > 0:
            _LLM_COST_USD.labels(*labels).inc(cost)
    except Exception:
        logger.warning("business_metrics_record_llm_usage_failed", exc_info=True)
        return


def record_tool_call(*, name: str, success: bool) -> None:
    if not _ensure_metrics():
        return
    try:
        _TOOL_CALLS.labels(_label(name, max_chars=80), "ok" if success else "failed").inc()
    except Exception:
        logger.warning("business_metrics_record_tool_call_failed", extra={"name": _label(name, max_chars=80)}, exc_info=True)
        return


def record_task_terminal(*, task_type: str, status: str) -> None:
    if not _ensure_metrics():
        return
    try:
        _TASK_TERMINALS.labels(_label(task_type, max_chars=80), _label(status, max_chars=30)).inc()
    except Exception:
        logger.warning(
            "business_metrics_record_task_terminal_failed",
            extra={"task_type": _label(task_type, max_chars=80), "status": _label(status, max_chars=30)},
            exc_info=True,
        )
        return
