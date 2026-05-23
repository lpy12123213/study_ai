from __future__ import annotations

import inspect
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from backend.core.logging_utils import get_logger
from backend.generation.question_library.gen_common import DEFAULT_SEARCH_CONFIG, _difficulty_rank
from backend.generation.question_library.stages import build_stage_progress_payload

logger = get_logger(__name__)

StageEventHandler = Optional[Callable[[dict], Awaitable[None] | None]]
ReasoningEventHandler = Optional[Callable[[dict], Awaitable[None] | None]]
CandidateAcceptedHandler = Optional[Callable[[dict], Awaitable[None] | None]]
GenerationSnapshotHandler = Optional[Callable[[dict], Awaitable[None] | None]]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _resolve_runtime_search_config(config: Optional[dict], *, count: int) -> dict:
    cfg = dict(DEFAULT_SEARCH_CONFIG)
    explicit = dict(config or {})
    cfg.update(explicit)

    target = max(1, min(int(count or 1), 10))
    if "beam_width" not in explicit:
        if target <= 3:
            cfg["beam_width"] = 6
        elif target >= 5:
            cfg["beam_width"] = 10
        else:
            cfg["beam_width"] = 8
    if "drafts_per_spec" not in explicit:
        cfg["drafts_per_spec"] = 2
    if "expand_budget" not in explicit:
        cfg["expand_budget"] = 60 if target <= 3 else 90 if target <= 5 else 120
    cfg["max_concurrent_realize"] = max(1, int(explicit.get("max_concurrent_realize") or 4))
    cfg["max_concurrent_judge"] = max(1, int(explicit.get("max_concurrent_judge") or 3))
    return cfg


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    return default


async def _emit_callback(handler: Optional[Callable[[dict], Awaitable[None] | None]], payload: dict) -> None:
    if handler is None:
        return
    try:
        result = handler(dict(payload))
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning("question_generation_callback_failed", exc_info=True)
        return


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "")
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def build_ai_question_id(*, now_ts: float | None = None, suffix: str = "") -> str:
    ts = time.localtime(now_ts if now_ts is not None else time.time())
    stamp = time.strftime("%Y%m%d%H%M", ts)
    suf = (suffix or "").strip() or "00000000"
    suf = suf[:8]
    return f"ai_{stamp}_{suf}"[:50]


def _summarize_candidate_sample(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        "spec_id": str(item.get("spec_id") or "").strip(),
        "seed_tag": str(item.get("seed_tag") or "").strip(),
        "skill": str(item.get("skill") or "").strip(),
        "reasoning": str(item.get("reasoning") or "").strip(),
        "trap": str(item.get("trap") or "").strip(),
        "surface": str(item.get("surface") or "").strip(),
        "stem_preview": _clip(str(item.get("stem") or "").strip(), 120),
    }


async def _emit_stage_event(
    on_stage_event: StageEventHandler,
    *,
    phase: str,
    label: str,
    progress: float,
    stats: Optional[dict] = None,
    sample: Optional[dict] = None,
) -> None:
    if on_stage_event is None:
        return

    payload = build_stage_progress_payload(
        str(phase or "").strip(),
        progress=float(progress),
        stats=stats,
        sample=sample,
        label=str(label or "").strip(),
    )

    try:
        result = on_stage_event(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning("question_generation_stage_event_failed", exc_info=True)
        return


def _tool_log_preview(value: Any, *, max_chars: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = repr(value)
    text = str(text or "").strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _tool_log_indent(text: str, *, prefix: str = "    ") -> str:
    raw = str(text or "").strip("\n")
    if not raw:
        return ""
    return "\n".join(prefix + line for line in raw.splitlines())


def _format_generation_tool_call_log(tool_name: str, arguments: Dict[str, Any]) -> str:
    return f"[tool_call] {tool_name}\n{_tool_log_indent(_tool_log_preview(arguments, max_chars=1600))}"


def _format_generation_tool_result_log(tool_name: str, result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return f"[tool_result] {tool_name}\n{_tool_log_indent(_tool_log_preview(result))}"

    summary: Dict[str, Any] = {}
    for key in ("success", "purpose", "result_type", "result_repr", "stdout", "warnings", "error"):
        if key in result and result.get(key) not in (None, "", [], {}):
            summary[key] = result.get(key)
    body = summary or result
    return f"[tool_result] {tool_name}\n{_tool_log_indent(_tool_log_preview(body, max_chars=1800))}"


def _get_env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _difficulty_gap_ratio(target: str, estimated: str) -> float:
    if not str(target or "").strip() or not str(estimated or "").strip():
        return 0.0
    return min(1.0, abs(_difficulty_rank(target) - _difficulty_rank(estimated)) / 2.0)


def _difficulty_mismatch_penalty(target: str, estimated: str, tolerance: float) -> int:
    gap = _difficulty_gap_ratio(target, estimated)
    if gap <= max(0.0, float(tolerance or 0.0)):
        return 0
    if gap >= 0.9:
        return 20
    return 12
