"""Shared leaf helpers for the ``question_generate`` CLI package.

This module is intentionally dependency-light (stdlib + ``backend.core``) so the
other submodules can import from it without creating circular imports. It holds
the time/path/model helpers, review-status normalisation, availability probes,
and the console factory used throughout the CLI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL, model_name, settings

_REVIEW_STATUSES = {"pending_review", "in_review", "approved", "rejected", "confirmed", "committed"}
# Keep the canonical logger name stable after the package split so emitted log
# events match the previous monolithic module.
logger = get_logger("backend.cli.question_generate")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _output_dir() -> Path:
    return (_repo_root() / "output").resolve()


def _looks_like_gpt_model(model: str) -> bool:
    raw = str(model or "").strip().lower()
    if not raw:
        return False
    if "/" in raw:
        raw = raw.split("/", 1)[-1]
    return raw.startswith("gpt-")


def _normalize_cli_model_for_provider(*, provider: str, model: str) -> str:
    provider_in = str(provider or "").strip().lower()
    model_in = str(model or "").strip()
    if provider_in == "ikuncode" and model_in.lower().startswith("openai/"):
        candidate = model_in.split("/", 1)[-1].strip()
        if _looks_like_gpt_model(candidate):
            return candidate
    return model_in


def _resolve_cli_mcp_search_model() -> str:
    explicit = model_name("question_library_mcp_search")
    if explicit:
        return explicit

    provider = str(
        getattr(settings, "lesson_plan_provider", "") or getattr(settings, "chat_provider", "")
    ).strip().lower()
    candidate_model = str(
        getattr(settings, "lesson_plan_model", "") or getattr(settings, "main_model", "") or LESSON_PLAN_MODEL
    )
    provider_model = _normalize_cli_model_for_provider(
        provider=provider,
        model=candidate_model,
    )
    if provider_model:
        return provider_model
    return str(getattr(settings, "main_model", "") or getattr(settings, "lesson_plan_model", "") or LESSON_PLAN_MODEL).strip()


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


def _normalize_review_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _REVIEW_STATUSES:
        return raw
    return "pending_review"


def _fmt_epoch(epoch_s: float) -> str:
    try:
        return datetime.fromtimestamp(float(epoch_s)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _infer_question_type_from_topic(topic: str) -> str:
    raw = str(topic or "")
    if "选择题" in raw and "解答题" in raw:
        return "选择题+解答题"
    for hint in ("选择题", "解答题", "填空题", "判断题", "证明题", "综合题", "问答题"):
        if hint in raw:
            return hint
    return ""


def _safe_user_id(user_id: str) -> str:
    uid = str(user_id or "").strip()
    return uid[:64] if uid else "1"


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401

        return True
    except ImportError:
        return False


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def _console():
    if _rich_available():
        from rich.console import Console

        return Console()

    class _PlainConsole:
        def print(self, *args, **kwargs):  # noqa: ANN001
            _ = kwargs
            print(*args)

        def rule(self, title: str = "") -> None:
            if title:
                print("=" * 8, title, "=" * 8)
            else:
                print("=" * 24)

    return _PlainConsole()
