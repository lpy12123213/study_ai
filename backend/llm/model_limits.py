from __future__ import annotations

import json
import math
import re
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import model_context_value
from backend.llm.tokenizer import estimate_messages_tokens
from backend.shared.project_paths import resolve_repo_local_dir

logger = get_logger(__name__)

_OPENROUTER_MODEL_LIMITS_CACHE: Dict[Tuple[str, str], Tuple[float, int, int]] = {}
_OPENROUTER_MODEL_LIMITS_CACHE_LOCK = threading.Lock()
_OPENROUTER_CACHE_FILE = (resolve_repo_local_dir() / "cache" / "openrouter_model_limits.json").resolve()


def maybe_append_v1_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    path = str(parts.path or "").rstrip("/")
    if path:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, "/v1", parts.query, parts.fragment)).rstrip("/")


def model_context_length(model: str) -> int:
    name = str(model or "").strip().lower()
    if not name:
        return 0
    builtin: Dict[str, int] = {"deepseek/deepseek-v3.2": 163840}
    configured = model_context_value("lengths", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            key = str(key or "").strip().lower()
            if key and parsed > 0:
                builtin[key] = parsed
    return int(builtin.get(name) or 0)


def _iter_env_pairs(raw: str):
    for part in re.split(r"[\n,;]+", raw):
        text = str(part or "").strip()
        if not text:
            continue
        if "=" in text:
            yield text.split("=", 1)
        elif ":" in text:
            yield text.split(":", 1)


def context_input_multiplier() -> float:
    try:
        value = float(model_context_value("input_multiplier", 1.15))
    except (TypeError, ValueError):
        value = 1.15
    return max(1.0, min(value if math.isfinite(value) else 1.15, 2.0))


def context_reserve_tokens(context_length: int) -> int:
    try:
        ctx_len = int(context_length)
    except (TypeError, ValueError):
        ctx_len = 0
    configured_reserve = model_context_value("reserve_tokens", None)
    if configured_reserve not in {None, "", 0, "0"}:
        try:
            reserve = int(configured_reserve)
        except (TypeError, ValueError):
            reserve = 1024
    else:
        try:
            ratio = float(model_context_value("reserve_ratio", 0.015))
        except (TypeError, ValueError):
            ratio = 0.015
        ratio = max(0.0, min(ratio if math.isfinite(ratio) else 0.015, 0.2))
        dyn = int(math.ceil(float(ctx_len) * ratio)) if ctx_len > 0 and ratio > 0 else 0
        reserve = max(1024, dyn) if dyn > 0 else 1024
    return int(max(128, min(int(reserve), 8192)))


def cap_max_tokens(
    *,
    messages: list[dict[str, Any]],
    context_length: int,
    requested_max_tokens: int,
    max_completion_tokens: int = 0,
) -> int:
    try:
        req = int(requested_max_tokens)
    except (TypeError, ValueError):
        req = 0
    if req <= 0:
        req = 1
    try:
        ctx_len = int(context_length)
    except (TypeError, ValueError):
        ctx_len = 0
    if ctx_len <= 0:
        return req
    input_tokens = int(math.ceil(float(estimate_messages_tokens(messages)) * context_input_multiplier()))
    allowed = int(ctx_len - input_tokens - context_reserve_tokens(ctx_len))
    try:
        max_comp = int(max_completion_tokens)
    except (TypeError, ValueError):
        max_comp = 0
    if max_comp > 0:
        allowed = min(allowed, max_comp)
    return 1 if allowed <= 0 else int(min(req, allowed))


def cap_max_tokens_for_messages(*, messages: list[dict[str, Any]], model: str, requested_max_tokens: int) -> int:
    return cap_max_tokens(messages=messages, context_length=model_context_length(model), requested_max_tokens=requested_max_tokens)


def parse_context_len_error(msg: str) -> Tuple[int, int, int]:
    text = str(msg or "")
    match = re.search(r"maximum context length is\s+(\d+)\s+tokens", text, flags=re.IGNORECASE)
    if not match:
        return (0, 0, 0)
    try:
        limit = int(match.group(1))
    except (TypeError, ValueError):
        limit = 0
    detail = re.search(r"\((\d+)\s+of\s+text\s+input,\s*(\d+)\s+in\s+the\s+output\)", text, flags=re.IGNORECASE)
    if not detail:
        return (limit, 0, 0)
    try:
        input_tokens, output_tokens = int(detail.group(1)), int(detail.group(2))
    except (TypeError, ValueError):
        return (limit, 0, 0)
    return (limit, input_tokens, output_tokens)


def _load_openrouter_model_limits_cache_from_disk() -> None:
    try:
        raw = _OPENROUTER_CACHE_FILE.read_text(encoding="utf-8")
        items = json.loads(raw).get("items") if raw.strip() else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return
    if not isinstance(items, list):
        return
    now = time.time()
    restored: Dict[Tuple[str, str], Tuple[float, int, int]] = {}
    for item in items[:50_000]:
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_url") or "").strip().rstrip("/")
        model = str(item.get("model") or "").strip().lower()
        try:
            expires, ctx_len, max_comp = float(item.get("expires_at") or 0), int(item.get("context_length") or 0), int(item.get("max_completion_tokens") or 0)
        except (TypeError, ValueError):
            continue
        if base and model and expires > now and ctx_len > 0:
            restored[(base, model)] = (expires, ctx_len, max_comp)
    if restored:
        with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
            _OPENROUTER_MODEL_LIMITS_CACHE.update(restored)


def _persist_openrouter_model_limits_cache_to_disk() -> None:
    try:
        _OPENROUTER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    now = time.time()
    with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
        items = [
            {"base_url": b, "model": m, "expires_at": v[0], "context_length": v[1], "max_completion_tokens": v[2]}
            for (b, m), v in _OPENROUTER_MODEL_LIMITS_CACHE.items()
            if isinstance(v, tuple) and len(v) == 3 and float(v[0]) > now and int(v[1]) > 0
        ]
    items.sort(key=lambda item: float(item.get("expires_at") or 0.0), reverse=True)
    try:
        _OPENROUTER_CACHE_FILE.write_text(
            json.dumps({"version": 1, "saved_at": now, "items": items[:5000]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


async def openrouter_model_limits(
    *, base_url: str, api_key: str, model: str, get_client: Callable[[], Awaitable[Any]], client_get: Callable[..., Awaitable[Any]]
) -> Tuple[int, int]:
    if not bool(model_context_value("openrouter_fetch_limits", True)):
        return (0, 0)
    base, model_key, key = str(base_url or "").strip().rstrip("/"), str(model or "").strip().lower(), str(api_key or "").strip()
    if not base or not model_key or not key:
        return (0, 0)
    try:
        ttl_s = max(10.0, min(float(model_context_value("openrouter_cache_ttl_s", 3600.0)), 24.0 * 3600.0))
    except (TypeError, ValueError):
        ttl_s = 3600.0
    now = time.time()
    with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
        cached = _OPENROUTER_MODEL_LIMITS_CACHE.get((base, model_key))
    if cached and float(cached[0]) > now:
        return (int(cached[1] or 0), int(cached[2] or 0))
    try:
        timeout_s = max(1.0, min(float(model_context_value("openrouter_timeout_s", 6.0)), 20.0))
        resp = await client_get(
            await get_client(),
            f"{base}/models",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout_s=timeout_s,
        )
        items = resp.json().get("data") if getattr(resp, "status_code", 0) == 200 else None
        if not isinstance(items, list):
            return (0, 0)
        ctx_len = max_comp = 0
        for item in items:
            if not isinstance(item, dict) or str(item.get("id") or "").strip().lower() != model_key:
                continue
            provider = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
            ctx_len = int(provider.get("context_length") or item.get("context_length") or 0)
            max_comp = int(provider.get("max_completion_tokens") or 0)
            break
    except (httpx.HTTPError, AttributeError, TypeError, ValueError):
        return (0, 0)
    if ctx_len > 0:
        with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
            _OPENROUTER_MODEL_LIMITS_CACHE[(base, model_key)] = (now + ttl_s, int(ctx_len), int(max_comp))
        _persist_openrouter_model_limits_cache_to_disk()
    return (int(ctx_len or 0), int(max_comp or 0))


_load_openrouter_model_limits_cache_from_disk()
