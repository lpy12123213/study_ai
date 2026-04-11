from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import threading
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from backend.llm import console as llm_console
from backend.core.logging_utils import get_logger
from backend.core.record_replay import RecordReplayStore, record_enabled, replay_enabled
from backend.core.settings import (
    API_TIMEOUT,
    CHAT_API_KEY,
    CHAT_BASE_URL,
    CHAT_PROVIDER,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_PROVIDER,
    LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD,
    LLM_CIRCUIT_BREAKER_OPEN_SECONDS,
    LLM_PROVIDER_PINNED,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
    REVIEW_HTTP_REFERER,
    REVIEW_X_TITLE,
)
from backend.llm.providers import resolve_provider
from backend.shared.project_paths import resolve_repo_local_dir

# Per-request LLM key overrides (e.g. provided by the frontend settings page).
# IMPORTANT: these values must never be persisted (tasks snapshots/events), only kept in-memory.
_llm_api_key_override_var: ContextVar[str] = ContextVar("llm_api_key_override", default="")
_moonshot_api_key_override_var: ContextVar[str] = ContextVar("moonshot_api_key_override", default="")

logger = get_logger(__name__)

_circuit_lock = threading.Lock()
# key -> {"fail_count": int, "open_until_s": float}
_circuit_state: Dict[str, Dict[str, Any]] = {}

# Optional: more accurate token counting (install `tiktoken` to enable).
_tiktoken_lock = threading.Lock()
_tiktoken_encoder = None
_tiktoken_encode_failed_logged = False


def _get_tiktoken_encoder():
    global _tiktoken_encoder
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    with _tiktoken_lock:
        if _tiktoken_encoder is not None:
            return _tiktoken_encoder
        try:
            import tiktoken  # type: ignore

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_encoder = None
        return _tiktoken_encoder


def _circuit_key(*, provider: str, model: str) -> str:
    return f"{str(provider or '').strip().lower()}:{str(model or '').strip()}"


def _circuit_is_open(key: str) -> Tuple[bool, float]:
    now = time.time()
    with _circuit_lock:
        st = _circuit_state.get(key) or {}
        try:
            open_until_s = float(st.get("open_until_s") or 0.0)
        except Exception:
            open_until_s = 0.0

        if open_until_s > now:
            return True, float(open_until_s - now)

        # Close the circuit once the open window expires.
        if open_until_s > 0.0:
            st["open_until_s"] = 0.0
            st["fail_count"] = 0
            _circuit_state[key] = st

    return False, 0.0


def _circuit_record_success(key: str) -> None:
    with _circuit_lock:
        _circuit_state[key] = {"fail_count": 0, "open_until_s": 0.0}


def _circuit_record_failure(key: str) -> None:
    threshold = int(LLM_CIRCUIT_BREAKER_FAIL_THRESHOLD or 0)
    open_s = float(LLM_CIRCUIT_BREAKER_OPEN_SECONDS or 0.0)
    if threshold <= 0 or open_s <= 0.0:
        return

    now = time.time()
    with _circuit_lock:
        st = _circuit_state.get(key) or {"fail_count": 0, "open_until_s": 0.0}
        try:
            st["fail_count"] = int(st.get("fail_count") or 0) + 1
        except Exception:
            st["fail_count"] = 1

        if int(st.get("fail_count") or 0) >= threshold:
            st["open_until_s"] = float(now + open_s)
        _circuit_state[key] = st


def set_llm_api_key_override(api_key: Optional[str]) -> Token:
    return _llm_api_key_override_var.set(str(api_key or "").strip())


def reset_llm_api_key_override(token: Token) -> None:
    _llm_api_key_override_var.reset(token)


def get_llm_api_key_override() -> str:
    return str(_llm_api_key_override_var.get() or "").strip()


def set_moonshot_api_key_override(api_key: Optional[str]) -> Token:
    return _moonshot_api_key_override_var.set(str(api_key or "").strip())


def reset_moonshot_api_key_override(token: Token) -> None:
    _moonshot_api_key_override_var.reset(token)


def get_moonshot_api_key_override() -> str:
    return str(_moonshot_api_key_override_var.get() or "").strip()


def is_llm_configured(*, scope: str = "lesson_plan") -> bool:
    """Whether the OpenAI-compatible LLM client is configured (best-effort).

    Scope is intentionally lightweight:
    - lesson_plan (default): match historical behavior (used by most agent paths)
    - chat: use CHAT_* config (used by the chat loop + sub-AI selector)
    - any: accept either config
    """

    scope_in = str(scope or "").strip().lower()
    if scope_in in {"chat", "main"}:
        return bool(
            get_llm_api_key_override()
            or get_moonshot_api_key_override()
            or str(CHAT_API_KEY or "").strip()
            or str(MOONSHOT_API_KEY or "").strip()
        )

    if scope_in in {"any", "all", "*"}:
        return bool(
            get_llm_api_key_override()
            or get_moonshot_api_key_override()
            or str(CHAT_API_KEY or "").strip()
            or str(LESSON_PLAN_API_KEY or "").strip()
            or str(MOONSHOT_API_KEY or "").strip()
        )

    return bool(
        get_llm_api_key_override()
        or get_moonshot_api_key_override()
        or str(LESSON_PLAN_API_KEY or "").strip()
        or str(MOONSHOT_API_KEY or "").strip()
    )


@dataclass
class ChatCompletionResult:
    content: str = ""
    finish_reason: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    # When `tools` are supplied, some providers return tool calls with an empty content channel.
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


def _elapsed_s(start_ts: float) -> float:
    if not start_ts:
        return 0.0
    try:
        return max(0.0, time.time() - float(start_ts))
    except Exception:
        return 0.0


def _resp_error(resp: Optional[httpx.Response]) -> str:
    if resp is None:
        return ""
    msg = ""
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or err.get("detail") or err.get("error") or "").strip()
            elif isinstance(err, str):
                msg = err.strip()
            if not msg:
                msg = str(data.get("message") or data.get("detail") or "").strip()
    except Exception:
        msg = ""
    if not msg:
        try:
            msg = str(resp.text or "").strip()
        except Exception:
            msg = ""
    if msg:
        msg = msg.replace("\n", " ").strip()
    return msg[:260]


def _model_context_length(model: str) -> int:
    m = str(model or "").strip().lower()
    if not m:
        return 0

    builtin: Dict[str, int] = {
        "deepseek/deepseek-v3.2": 163840,
    }

    raw = str(os.getenv("MODEL_CONTEXT_LENGTHS") or "").strip()
    if raw:
        try:
            if raw.startswith("{"):
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        kk = str(k or "").strip().lower()
                        try:
                            vv = int(v)
                        except Exception:
                            continue
                        if kk and vv > 0:
                            builtin[kk] = vv
            else:
                parts = re.split(r"[\n,;]+", raw)
                for p in parts:
                    p = str(p or "").strip()
                    if not p:
                        continue
                    if "=" in p:
                        k, v = p.split("=", 1)
                    elif ":" in p:
                        k, v = p.split(":", 1)
                    else:
                        continue
                    kk = str(k or "").strip().lower()
                    try:
                        vv = int(str(v or "").strip())
                    except Exception:
                        continue
                    if kk and vv > 0:
                        builtin[kk] = vv
        except Exception:
            logger.debug("failed to parse builtin model max tokens", exc_info=True)

    return int(builtin.get(m) or 0)


def _estimate_text_tokens(text: str) -> int:
    t = str(text or "")
    if not t:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None:
        # Tokenizing extremely large blobs can be expensive; fall back to heuristic.
        if len(t) <= 50_000:
            try:
                return int(len(enc.encode(t)))
            except Exception:
                global _tiktoken_encode_failed_logged
                if not _tiktoken_encode_failed_logged:
                    _tiktoken_encode_failed_logged = True
                    logger.warning("tiktoken_encode_failed_fallback", exc_info=True)
    cjk = 0
    for ch in t:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF:
            cjk += 1
    ratio = float(cjk) / float(len(t) or 1)
    if ratio >= 0.25:
        return int(math.ceil(len(t) / 1.6))
    return int(math.ceil(len(t) / 4.0))


def _estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        total += 6
        total += _estimate_text_tokens(role)
        total += _estimate_text_tokens(content)
    return int(total)


def _context_input_multiplier() -> float:
    raw = str(os.getenv("MODEL_CONTEXT_INPUT_MULTIPLIER") or "").strip()
    try:
        v = float(raw) if raw else 1.15
    except Exception:
        v = 1.15
    if not math.isfinite(v):
        v = 1.15
    return max(1.0, min(v, 2.0))


def _context_reserve_tokens(context_length: int) -> int:
    try:
        ctx_len = int(context_length)
    except Exception:
        ctx_len = 0

    reserve_raw = str(os.getenv("MODEL_CONTEXT_RESERVE_TOKENS") or "").strip()
    if reserve_raw:
        try:
            reserve = int(reserve_raw)
        except Exception:
            reserve = 1024
    else:
        ratio_raw = str(os.getenv("MODEL_CONTEXT_RESERVE_RATIO") or "").strip()
        try:
            ratio = float(ratio_raw) if ratio_raw else 0.015
        except Exception:
            ratio = 0.015
        if not math.isfinite(ratio):
            ratio = 0.015
        ratio = max(0.0, min(ratio, 0.2))
        dyn = int(math.ceil(float(ctx_len) * float(ratio))) if (ctx_len > 0 and ratio > 0) else 0
        reserve = max(1024, dyn) if dyn > 0 else 1024

    reserve = max(128, min(int(reserve), 8192))
    return int(reserve)


def cap_max_tokens_for_messages(
    *,
    messages: List[Dict[str, str]],
    model: str,
    requested_max_tokens: int,
) -> int:
    try:
        req = int(requested_max_tokens)
    except Exception:
        req = 0
    if req <= 0:
        req = 1

    ctx_len = _model_context_length(model)
    if ctx_len <= 0:
        return req

    reserve = _context_reserve_tokens(ctx_len)

    in_tokens = _estimate_messages_tokens(messages)
    mult = _context_input_multiplier()
    if mult > 1.0:
        in_tokens = int(math.ceil(float(in_tokens) * float(mult)))
    allowed = int(ctx_len - in_tokens - reserve)
    if allowed <= 0:
        return 1
    return int(min(req, allowed))


def _parse_context_len_error(msg: str) -> Tuple[int, int, int]:
    s = str(msg or "")
    if not s:
        return (0, 0, 0)
    m1 = re.search(r"maximum context length is\s+(\d+)\s+tokens", s, flags=re.IGNORECASE)
    if not m1:
        return (0, 0, 0)
    try:
        limit = int(m1.group(1))
    except Exception:
        limit = 0
    m2 = re.search(r"\((\d+)\s+of\s+text\s+input,\s*(\d+)\s+in\s+the\s+output\)", s, flags=re.IGNORECASE)
    in_t = 0
    out_t = 0
    if m2:
        try:
            in_t = int(m2.group(1))
        except Exception:
            in_t = 0
        try:
            out_t = int(m2.group(2))
        except Exception:
            out_t = 0
    return (limit, in_t, out_t)


_OPENROUTER_MODEL_LIMITS_CACHE: Dict[Tuple[str, str], Tuple[float, int, int]] = {}
_OPENROUTER_MODEL_LIMITS_CACHE_LOCK = threading.Lock()
_OPENROUTER_CACHE_FILE: Path = (resolve_repo_local_dir() / "cache" / "openrouter_model_limits.json").resolve()


def _load_openrouter_model_limits_cache_from_disk() -> None:
    """Best-effort persistent cache for OpenRouter /models limits.

    This avoids re-fetching `/models` after every worker restart.
    """

    path = _OPENROUTER_CACHE_FILE
    try:
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw) if raw.strip() else {}
    except Exception:
        return

    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return

    now = time.time()
    restored: Dict[Tuple[str, str], Tuple[float, int, int]] = {}
    for it in items[:50_000]:
        if not isinstance(it, dict):
            continue
        b = str(it.get("base_url") or "").strip().rstrip("/")
        m = str(it.get("model") or "").strip().lower()
        try:
            exp = float(it.get("expires_at") or 0.0)
        except Exception:
            exp = 0.0
        try:
            ctx_len = int(it.get("context_length") or 0)
        except Exception:
            ctx_len = 0
        try:
            max_comp = int(it.get("max_completion_tokens") or 0)
        except Exception:
            max_comp = 0
        if not b or not m or exp <= now or ctx_len <= 0:
            continue
        restored[(b, m)] = (exp, ctx_len, max_comp)

    if not restored:
        return
    with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
        _OPENROUTER_MODEL_LIMITS_CACHE.update(restored)


def _persist_openrouter_model_limits_cache_to_disk() -> None:
    path = _OPENROUTER_CACHE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    now = time.time()
    with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
        items = [
            {
                "base_url": b,
                "model": m,
                "expires_at": float(v[0]),
                "context_length": int(v[1]),
                "max_completion_tokens": int(v[2]),
            }
            for (b, m), v in _OPENROUTER_MODEL_LIMITS_CACHE.items()
            if isinstance(v, tuple) and len(v) == 3 and float(v[0]) > now and int(v[1]) > 0
        ]

    # Keep the file bounded (largest wins: farthest expiry first).
    items.sort(key=lambda x: float(x.get("expires_at") or 0.0), reverse=True)
    items = items[:5000]
    payload = {"version": 1, "saved_at": now, "items": items}
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


_load_openrouter_model_limits_cache_from_disk()


def _cap_max_tokens_with_ctx_len(
    *,
    messages: List[Dict[str, str]],
    context_length: int,
    requested_max_tokens: int,
    max_completion_tokens: int = 0,
) -> int:
    try:
        req = int(requested_max_tokens)
    except Exception:
        req = 0
    if req <= 0:
        req = 1

    try:
        ctx_len = int(context_length)
    except Exception:
        ctx_len = 0
    if ctx_len <= 0:
        return req

    reserve = _context_reserve_tokens(ctx_len)

    in_tokens = _estimate_messages_tokens(messages)
    mult = _context_input_multiplier()
    if mult > 1.0:
        in_tokens = int(math.ceil(float(in_tokens) * float(mult)))
    allowed = int(ctx_len - int(in_tokens) - int(reserve))
    if max_completion_tokens:
        try:
            mct = int(max_completion_tokens)
        except Exception:
            mct = 0
        if mct > 0:
            allowed = int(min(allowed, mct))

    if allowed <= 0:
        return 1
    return int(min(req, allowed))


async def _openrouter_model_limits(
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> Tuple[int, int]:
    fetch_raw = str(os.getenv("OPENROUTER_FETCH_MODEL_LIMITS") or "1").strip().lower()
    if fetch_raw in {"0", "false", "no", "off"}:
        return (0, 0)

    b = str(base_url or "").strip().rstrip("/")
    m = str(model or "").strip().lower()
    k = str(api_key or "").strip()
    if not b or not m or not k:
        return (0, 0)

    ttl_raw = str(os.getenv("OPENROUTER_MODELS_CACHE_TTL_S") or "").strip()
    try:
        ttl_s = float(ttl_raw) if ttl_raw else 3600.0
    except Exception:
        ttl_s = 3600.0
    ttl_s = max(10.0, min(ttl_s, 24.0 * 3600.0))

    now = time.time()
    cache_key = (b, m)
    with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
        cached = _OPENROUTER_MODEL_LIMITS_CACHE.get(cache_key)
    if cached and float(cached[0]) > now:
        return (int(cached[1] or 0), int(cached[2] or 0))

    timeout_raw = str(os.getenv("OPENROUTER_MODELS_TIMEOUT_S") or "").strip()
    try:
        timeout_s = float(timeout_raw) if timeout_raw else 6.0
    except Exception:
        timeout_s = 6.0
    timeout_s = max(1.0, min(timeout_s, 20.0))

    ctx_len = 0
    max_comp = 0
    try:
        headers = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(f"{b}/models", headers=headers)
        if resp.status_code != 200:
            return (0, 0)
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return (0, 0)
        for it in items:
            if not isinstance(it, dict):
                continue
            mid = str(it.get("id") or "").strip().lower()
            if mid != m:
                continue
            try:
                ctx_len = int(it.get("context_length") or 0)
            except Exception:
                ctx_len = 0
            tp = it.get("top_provider") if isinstance(it.get("top_provider"), dict) else {}
            try:
                tp_ctx = int(tp.get("context_length") or 0)
            except Exception:
                tp_ctx = 0
            try:
                max_comp = int(tp.get("max_completion_tokens") or 0)
            except Exception:
                max_comp = 0
            if tp_ctx > 0:
                ctx_len = tp_ctx
            break
    except Exception:
        return (0, 0)

    if ctx_len > 0:
        with _OPENROUTER_MODEL_LIMITS_CACHE_LOCK:
            _OPENROUTER_MODEL_LIMITS_CACHE[cache_key] = (now + ttl_s, int(ctx_len), int(max_comp))
        _persist_openrouter_model_limits_cache_to_disk()
    return (int(ctx_len or 0), int(max_comp or 0))


async def chat_completion(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    stream: bool = False,
    on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    reasoning_emit_chars: int = 240,
    reasoning_emit_interval_s: float = 0.25,
    raise_on_fail: bool = False,
    retries: int = 3,
    timeout_s: Optional[float] = None,
    req_id_prefix: str = "llm",
    scope: str = "lesson_plan",
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    moonshot_key: Optional[str] = None,
    moonshot_base_url: Optional[str] = None,
) -> ChatCompletionResult:
    """
    Call an OpenAI-compatible `POST /chat/completions` endpoint.

    - Supports OpenRouter-style streamed "reasoning" deltas (best-effort).
    - Returns accumulated content + finish_reason + usage.
    """

    scope_in = str(scope or "").strip().lower()
    if scope_in in {"chat", "main"}:
        default_provider = CHAT_PROVIDER
        default_base_url = CHAT_BASE_URL
        default_api_key = CHAT_API_KEY
    else:
        default_provider = LESSON_PLAN_PROVIDER
        default_base_url = LESSON_PLAN_BASE_URL
        default_api_key = LESSON_PLAN_API_KEY

    provider_in = str(provider or default_provider or "").strip().lower() or "openrouter"
    base_url_in = str(base_url or default_base_url or "").strip().rstrip("/")

    api_key_in = str(api_key or "").strip() or str(_llm_api_key_override_var.get() or "").strip()
    if not api_key_in:
        api_key_in = str(default_api_key or "").strip()

    moonshot_key_in = str(moonshot_key or "").strip() or str(_moonshot_api_key_override_var.get() or "").strip()
    if not moonshot_key_in:
        moonshot_key_in = str(MOONSHOT_API_KEY or "").strip()

    moonshot_base_url_in = str(moonshot_base_url or MOONSHOT_BASE_URL or "").strip().rstrip("/")

    resolved_provider, resolved_base_url, resolved_api_key, resolved_model = resolve_provider(
        provider=provider_in,
        base_url=base_url_in,
        api_key=api_key_in,
        model=str(model or "").strip(),
        moonshot_key=moonshot_key_in,
        moonshot_base_url=moonshot_base_url_in,
        allow_moonshot_auto_switch=not bool(LLM_PROVIDER_PINNED),
    )

    effective_temperature = float(temperature)
    if resolved_provider == "moonshot" and resolved_model.lower().startswith("kimi-"):
        # Moonshot kimi models reject temperatures other than 1.0 (HTTP 400).
        effective_temperature = 1.0

    rr_store = RecordReplayStore("llm")
    rr_request = {
        "provider": resolved_provider,
        "base_url": resolved_base_url,
        "model": resolved_model,
        "messages": messages,
        "temperature": effective_temperature,
        "max_tokens": int(max_tokens),
        "response_format": response_format or None,
        "reasoning": reasoning or None,
        "tools": tools or None,
        "tool_choice": tool_choice or None,
        "stream": bool(stream),
    }

    if replay_enabled():
        fixture, key = rr_store.load(request=rr_request)
        resp = fixture.get("response") if isinstance(fixture, dict) else None
        if isinstance(resp, dict):
            usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
            return ChatCompletionResult(
                content=str(resp.get("content") or ""),
                finish_reason=str(resp.get("finish_reason") or ""),
                usage=dict(usage),
                tool_calls=list(resp.get("tool_calls") or []) if isinstance(resp.get("tool_calls"), list) else [],
            )
        if not record_enabled():
            if raise_on_fail:
                raise RuntimeError(f"replay_fixture_missing key={key}")
            return ChatCompletionResult()

    if not resolved_api_key:
        if raise_on_fail:
            raise RuntimeError("llm_not_configured")
        return ChatCompletionResult()

    req_id_base = f"{req_id_prefix}-{uuid.uuid4().hex[:8]}"
    request_timeout_s = float(timeout_s) if timeout_s is not None else float(API_TIMEOUT or 120)
    request_timeout_s = max(1.0, min(request_timeout_s, 600.0))

    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    max_retries = max(1, min(int(retries or 3), 10))
    last_error = ""

    circuit_key = _circuit_key(provider=resolved_provider, model=resolved_model)
    circuit_open, circuit_wait_s = _circuit_is_open(circuit_key)
    if circuit_open:
        last_error = f"llm_circuit_open wait_s={circuit_wait_s:.1f}"
        llm_console.log_end(req_id=f"{req_id_base}-cb", elapsed_s=0.0, error=last_error)
        if raise_on_fail:
            raise RuntimeError("llm_circuit_open")
        return ChatCompletionResult()

    headers = {"Authorization": f"Bearer {resolved_api_key}", "Content-Type": "application/json"}
    if resolved_provider == "openrouter":
        if str(REVIEW_HTTP_REFERER or "").strip():
            headers["HTTP-Referer"] = str(REVIEW_HTTP_REFERER or "").strip()
        if str(REVIEW_X_TITLE or "").strip():
            headers["X-Title"] = str(REVIEW_X_TITLE or "").strip()

    requested_max_tokens = int(max_tokens)
    # max_tokens <= 0 means "unlimited" – omit the field from the payload so
    # the API uses the model's default maximum output length.
    payload_max_tokens = 0
    if requested_max_tokens > 0:
        if resolved_provider == "openrouter":
            ctx_len, max_comp = await _openrouter_model_limits(
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                model=resolved_model,
            )
            if ctx_len > 0:
                payload_max_tokens = _cap_max_tokens_with_ctx_len(
                    messages=messages,
                    context_length=ctx_len,
                    requested_max_tokens=requested_max_tokens,
                    max_completion_tokens=max_comp,
                )

        if payload_max_tokens <= 0:
            payload_max_tokens = cap_max_tokens_for_messages(
                messages=messages,
                model=resolved_model,
                requested_max_tokens=requested_max_tokens,
            )

    payload: Dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": effective_temperature,
        "stream": False,
    }
    if payload_max_tokens > 0:
        payload["max_tokens"] = int(payload_max_tokens)

    if isinstance(response_format, dict) and response_format:
        payload["response_format"] = dict(response_format)

    if isinstance(tools, list) and tools:
        payload["tools"] = list(tools)
        payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"

    is_openrouter = resolved_provider == "openrouter"
    if stream and resolved_provider in {"openrouter", "moonshot"}:
        payload["stream"] = True

    if isinstance(reasoning, dict) and reasoning:
        # OpenRouter's "reasoning" feature can cause some models (notably DeepSeek)
        # to emit the entire completion as reasoning with an empty `message.content`.
        # When we are not streaming, this client only reads `message.content`, so keep
        # reasoning disabled to avoid returning an empty string to downstream JSON parsers.
        if is_openrouter and (not stream) and str(resolved_model or "").strip().lower().startswith("deepseek/"):
            pass
        else:
            payload["reasoning"] = dict(reasoning)

    dropped_reasoning = False
    dropped_response_format = False

    reasoning_emit_chars = int(reasoning_emit_chars or 0)
    if reasoning_emit_chars <= 0:
        reasoning_emit_chars = 240
    reasoning_emit_interval_s = float(reasoning_emit_interval_s or 0.0)
    reasoning_emit_interval_s = max(0.05, min(reasoning_emit_interval_s, 2.0))

    url = f"{resolved_base_url}/chat/completions"

    async def _maybe_emit_reasoning(buf: str) -> None:
        if not buf:
            return
        if on_reasoning_delta is None:
            return
        try:
            await on_reasoning_delta(buf)
        except Exception:
            # Best-effort; never fail the request due to UI emission errors.
            return

    for attempt in range(max_retries):
        req_id = f"{req_id_base}-{attempt + 1}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=resolved_provider,
            model=resolved_model,
            stream=bool(payload.get("stream")),
            temperature=float(payload.get("temperature") or 0.0),
            max_tokens=int(payload.get("max_tokens") or 0),
            base_url=resolved_base_url,
        )
        try:
            async with httpx.AsyncClient(timeout=request_timeout_s, follow_redirects=True) as client:
                if bool(payload.get("stream")):
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                            retry_after = (resp.headers.get("retry-after") or "").strip()
                            wait_s = 0.0
                            try:
                                wait_s = float(retry_after) if retry_after else 0.0
                            except ValueError:
                                wait_s = 0.0
                            if wait_s <= 0:
                                wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                            last_error = f"http_status_{resp.status_code}"
                            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                            await asyncio.sleep(wait_s)
                            continue

                        if resp.status_code != 200:
                            try:
                                await resp.aread()
                            except Exception:
                                logger.debug(
                                    "llm_response_drain_failed",
                                    extra={"status": int(getattr(resp, "status_code", 0) or 0)},
                                    exc_info=True,
                                )
                        resp.raise_for_status()

                        content_parts: List[str] = []
                        finish_reason = ""
                        usage: Dict[str, Any] = {}

                        reasoning_buf = ""
                        loop = asyncio.get_running_loop()
                        last_emit_t = loop.time()

                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            if line.startswith(":"):
                                continue
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data:
                                continue
                            if data == "[DONE]":
                                break

                            try:
                                obj = json.loads(data)
                            except Exception:
                                continue

                            choices = obj.get("choices")
                            if not isinstance(choices, list) or not choices:
                                continue
                            choice0 = choices[0] if isinstance(choices[0], dict) else {}
                            delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}

                            r_chunk = ""
                            details = delta.get("reasoning_details")
                            if isinstance(details, list) and details:
                                text_parts: List[str] = []
                                summary_parts: List[str] = []
                                for it in details:
                                    if not isinstance(it, dict):
                                        continue
                                    if isinstance(it.get("text"), str) and it.get("text"):
                                        text_parts.append(str(it.get("text") or ""))
                                    elif isinstance(it.get("summary"), str) and it.get("summary"):
                                        summary_parts.append(str(it.get("summary") or ""))
                                if text_parts:
                                    r_chunk = "".join(text_parts)
                                elif summary_parts:
                                    r_chunk = "".join(summary_parts)
                            elif isinstance(delta.get("reasoning_content"), str):
                                r_chunk = str(delta.get("reasoning_content") or "")
                            elif isinstance(delta.get("reasoning"), str):
                                r_chunk = str(delta.get("reasoning") or "")

                            if r_chunk:
                                reasoning_buf += r_chunk
                                now_t = loop.time()
                                if (
                                    len(reasoning_buf) >= reasoning_emit_chars
                                    or (now_t - last_emit_t) >= reasoning_emit_interval_s
                                ):
                                    await _maybe_emit_reasoning(reasoning_buf)
                                    llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)
                                    reasoning_buf = ""
                                    last_emit_t = now_t

                            c_chunk = delta.get("content")
                            if isinstance(c_chunk, str) and c_chunk:
                                content_parts.append(c_chunk)
                                llm_console.log_delta(req_id=req_id, channel="content", text=c_chunk)
                                if on_content_delta is not None:
                                    try:
                                        await on_content_delta(c_chunk)
                                    except Exception:
                                        logger.debug(
                                            "llm_on_content_delta_failed",
                                            extra={"provider": resolved_provider, "model": resolved_model},
                                            exc_info=True,
                                        )

                            fr_chunk = choice0.get("finish_reason")
                            if isinstance(fr_chunk, str) and fr_chunk:
                                finish_reason = fr_chunk

                            if isinstance(obj.get("usage"), dict):
                                usage = dict(obj.get("usage") or {})

                        if reasoning_buf:
                            await _maybe_emit_reasoning(reasoning_buf)
                            llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)

                        content_text = "".join(content_parts)
                        llm_console.log_end(
                            req_id=req_id,
                            elapsed_s=_elapsed_s(start_ts),
                            finish_reason=finish_reason,
                            usage=usage,
                            content_chars=len(content_text),
                        )
                        result = ChatCompletionResult(content=content_text, finish_reason=finish_reason, usage=usage)
                        if record_enabled():
                            rr_store.save(
                                request=rr_request,
                                response={
                                    "content": result.content,
                                    "finish_reason": result.finish_reason,
                                    "usage": result.usage,
                                },
                            )
                        _circuit_record_success(circuit_key)
                        return result

                resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                retry_after = (resp.headers.get("retry-after") or "").strip()
                wait_s = 0.0
                try:
                    wait_s = float(retry_after) if retry_after else 0.0
                except ValueError:
                    wait_s = 0.0
                if wait_s <= 0:
                    wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                last_error = f"http_status_{resp.status_code}"
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                await asyncio.sleep(wait_s)
                continue

            resp.raise_for_status()
            data = resp.json()
            try:
                choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                message0 = choice0.get("message", {}) if isinstance(choice0, dict) else {}
                tool_calls_raw = message0.get("tool_calls")
                tool_calls: List[Dict[str, Any]] = (
                    list(tool_calls_raw) if isinstance(tool_calls_raw, list) else []
                )

                content = str(message0.get("content") or "").strip()
                finish_reason = ""
                usage: Dict[str, Any] = {}
                try:
                    finish_reason = str(choice0.get("finish_reason") or "") if isinstance(choice0, dict) else ""
                except Exception:
                    finish_reason = ""
                if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                    usage = dict(data.get("usage") or {})
                # OpenRouter can return an empty content when "reasoning" is enabled
                # (especially with exclude=true). Retry once without `reasoning` to
                # recover a normal content channel for downstream parsing.
                if (not content) and (not tool_calls) and (not dropped_reasoning) and ("reasoning" in payload):
                    payload.pop("reasoning", None)
                    dropped_reasoning = True
                    last_error = "empty_content_drop_reasoning"
                    logger.warning(
                        "llm_empty_content_drop_reasoning",
                        extra={
                            "req_id": req_id,
                            "model": resolved_model,
                            "provider": resolved_provider,
                            "base_url": resolved_base_url,
                        },
                    )
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue
                if content:
                    llm_console.log_delta(req_id=req_id, channel="content", text=content)
                llm_console.log_end(
                    req_id=req_id,
                    elapsed_s=_elapsed_s(start_ts),
                    finish_reason=finish_reason,
                    usage=usage,
                    content_chars=len(content),
                )
                result = ChatCompletionResult(content=content, finish_reason=finish_reason, usage=usage, tool_calls=tool_calls)
                if record_enabled():
                    rr_store.save(
                        request=rr_request,
                        response={
                            "content": result.content,
                            "finish_reason": result.finish_reason,
                            "usage": result.usage,
                            "tool_calls": result.tool_calls,
                        },
                    )
                _circuit_record_success(circuit_key)
                return result
            except Exception:
                last_error = "invalid_response"
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if attempt < (max_retries - 1):
                    await asyncio.sleep(min(3.0, 0.4 + random.random() * 0.8))
                    continue
                if raise_on_fail:
                    raise RuntimeError(f"llm_invalid_response model={resolved_model}")
                _circuit_record_failure(circuit_key)
                return ChatCompletionResult()

        except asyncio.CancelledError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            api_msg = _resp_error(exc.response)
            last_error = f"http_status_{status}"

            if status in {400, 422}:
                limit, in_t, _out_t = _parse_context_len_error(api_msg)
                if limit > 0:
                    if in_t <= 0:
                        in_t = _estimate_messages_tokens(messages)
                        mult = _context_input_multiplier()
                        if mult > 1.0:
                            in_t = int(math.ceil(float(in_t) * float(mult)))
                    reserve = _context_reserve_tokens(limit)
                    new_allowed = int(limit - int(in_t) - reserve)
                    if new_allowed > 0:
                        try:
                            cur = int(payload.get("max_tokens") or 0)
                        except Exception:
                            cur = 0
                        if cur > new_allowed:
                            payload["max_tokens"] = int(new_allowed)
                            llm_console.log_end(
                                req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error
                            )
                            await asyncio.sleep(0.2)
                            continue

                if resolved_provider == "moonshot":
                    msg_l = (api_msg or "").lower()
                    try:
                        current_t = float(payload.get("temperature") or 0.0)
                    except Exception:
                        current_t = 0.0
                    if ("temperature" in msg_l and "only 1" in msg_l) and current_t != 1.0:
                        payload["temperature"] = 1.0
                        llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                        await asyncio.sleep(0.2)
                        continue

                # Some models/providers reject unknown fields. Retry after dropping them (once each).
                if (not dropped_response_format) and ("response_format" in payload):
                    payload.pop("response_format", None)
                    dropped_response_format = True
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue

                if (not dropped_reasoning) and ("reasoning" in payload):
                    payload.pop("reasoning", None)
                    dropped_reasoning = True
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue

            if status in retry_statuses and attempt < (max_retries - 1):
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue

            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
            if raise_on_fail:
                raise RuntimeError(
                    f"llm_request_failed status={status} model={resolved_model} provider={resolved_provider} msg={api_msg or last_error}"
                )
            _circuit_record_failure(circuit_key)
            return ChatCompletionResult()
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_error = str(exc)
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
            if attempt < (max_retries - 1):
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
            _circuit_record_failure(circuit_key)
            return ChatCompletionResult()
        except Exception as exc:  # pragma: no cover (best-effort)
            last_error = str(exc)
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
            if attempt < (max_retries - 1):
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error}")
            _circuit_record_failure(circuit_key)
            return ChatCompletionResult()

    if last_error:
        logger.warning("llm request failed after retries", extra={"error": last_error, "model": resolved_model})
    if raise_on_fail:
        raise RuntimeError(f"llm_request_failed model={resolved_model} err={last_error or 'unknown'}")
    _circuit_record_failure(circuit_key)
    return ChatCompletionResult()


async def chat_completion_text(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning: Optional[Dict[str, Any]] = None,
    stream: bool = False,
    on_reasoning_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    reasoning_emit_chars: int = 240,
    reasoning_emit_interval_s: float = 0.25,
    raise_on_fail: bool = False,
    retries: int = 3,
    timeout_s: Optional[float] = None,
    req_id_prefix: str = "llm",
    scope: str = "lesson_plan",
) -> str:
    res = await chat_completion(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        reasoning=reasoning,
        stream=stream,
        on_reasoning_delta=on_reasoning_delta,
        on_content_delta=on_content_delta,
        reasoning_emit_chars=reasoning_emit_chars,
        reasoning_emit_interval_s=reasoning_emit_interval_s,
        raise_on_fail=raise_on_fail,
        retries=retries,
        timeout_s=timeout_s,
        req_id_prefix=req_id_prefix,
        scope=scope,
    )
    return str(res.content or "")
