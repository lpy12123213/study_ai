from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Optional


def _truthy(raw: str) -> bool:
    s = (raw or "").strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def enabled() -> bool:
    # Default behavior:
    # - When `LOG_FORMAT=json` (server/structured logs), keep this OFF by default to avoid mixed log formats.
    # - Otherwise (local debugging), keep it ON by default.
    #
    # Override with `LLM_CONSOLE_LOG=1|0`.
    raw = os.getenv("LLM_CONSOLE_LOG")
    if raw is None:
        fmt = str(os.getenv("LOG_FORMAT") or "json").strip().lower()
        raw = "0" if fmt == "json" else "1"
    return _truthy(raw)


def stream_enabled() -> bool:
    # Whether to print streaming deltas (not whether the upstream API uses stream=true).
    raw = os.getenv("LLM_CONSOLE_STREAM")
    if raw is None:
        raw = "1"
    return _truthy(raw)


def _max_delta_chars() -> int:
    raw = (os.getenv("LLM_CONSOLE_DELTA_MAX_CHARS") or "").strip()
    if not raw:
        return 3000
    try:
        v = int(raw)
    except Exception:
        v = 3000
    return max(0, min(v, 20000))


def _safe_print(line: str) -> None:
    try:
        print(line, flush=True)
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return

    try:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((line + "\n").encode(enc, errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        return


def log_start(
    *,
    req_id: str,
    provider: str,
    model: str,
    stream: bool,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    base_url: str = "",
) -> float:
    """Return start timestamp (time.time()) to compute elapsed time later."""
    if not enabled():
        return 0.0
    extras = []
    if temperature is not None:
        extras.append(f"temp={temperature}")
    if max_tokens is not None:
        extras.append(f"max_tokens={max_tokens}")
    if base_url and _truthy(os.getenv("LLM_CONSOLE_LOG_URL") or "0"):
        extras.append(f"base_url={base_url}")
    extra_s = (" " + " ".join(extras)) if extras else ""
    _safe_print(f"[llm:{req_id}] start provider={provider} model={model} stream={bool(stream)}{extra_s}")
    return time.time()


def log_delta(*, req_id: str, channel: str, text: str) -> None:
    if not (enabled() and stream_enabled()):
        return
    t = str(text or "")
    if not t:
        return
    # Keep each console line bounded and robust on Windows consoles.
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    max_chars = _max_delta_chars()
    if max_chars > 0 and len(t) > max_chars:
        t = t[: max_chars - 1] + "…"
    _safe_print(f"[llm:{req_id}][{channel}] {t}")


def log_end(
    *,
    req_id: str,
    elapsed_s: float = 0.0,
    finish_reason: str = "",
    usage: Optional[Dict[str, Any]] = None,
    content_chars: Optional[int] = None,
    error: str = "",
) -> None:
    if not enabled():
        return
    parts = []
    if elapsed_s > 0:
        parts.append(f"{elapsed_s:.2f}s")
    if finish_reason:
        parts.append(f"finish={finish_reason}")
    if isinstance(usage, dict) and usage:
        # Common OpenAI-compatible usage fields
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        usage_bits = []
        if isinstance(pt, int):
            usage_bits.append(f"prompt={pt}")
        if isinstance(ct, int):
            usage_bits.append(f"completion={ct}")
        if isinstance(tt, int):
            usage_bits.append(f"total={tt}")
        if usage_bits:
            parts.append("usage(" + ",".join(usage_bits) + ")")
    if isinstance(content_chars, int):
        parts.append(f"chars={content_chars}")
    if error:
        parts.append(f"error={error}")
    suffix = (" " + " ".join(parts)) if parts else ""
    _safe_print(f"[llm:{req_id}] end{suffix}")
