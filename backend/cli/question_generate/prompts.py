"""Interactive prompt helpers, banners and session pickers for the CLI.

These wrap ``prompt_toolkit``/``rich`` when available and fall back to plain
``input``/``print`` so the generator stays usable in minimal terminals.
"""

from __future__ import annotations

import asyncio
import os
from typing import List

from backend.generation.question_library.preview_store import (
    list_sessions as list_saved_sessions,
)

from .helpers import (
    _fmt_epoch,
    _prompt_toolkit_available,
    _resolve_cli_mcp_search_model,
    _rich_available,
    logger,
)
from .session import _normalize_draft_questions


def _prompt_text(label: str, *, default: str = "") -> str:
    prompt_label = f"{label}"
    if default:
        prompt_label += f" (默认: {default})"
    prompt_label += ": "

    # prompt_toolkit's sync prompt internally uses asyncio.run(); it will crash if
    # called inside an already-running event loop. This CLI is mostly synchronous
    # around prompting, but keep a safe fallback for environments like notebooks.
    in_running_loop = False
    try:
        asyncio.get_running_loop()
        in_running_loop = True
    except RuntimeError:
        in_running_loop = False

    if _prompt_toolkit_available() and not in_running_loop:
        try:
            from prompt_toolkit import prompt as pt_prompt

            value = pt_prompt(prompt_label, default=str(default or ""))
            return str(value or "").strip() or str(default or "").strip()
        except RuntimeError:
            # Fall back to builtin input when prompt_toolkit can't run.
            pass

    value = input(prompt_label)
    return str(value or "").strip() or str(default or "").strip()


def _prompt_choice(label: str, options: List[str], *, default: str) -> str:
    choices = [str(x).strip() for x in options if str(x).strip()]
    if not choices:
        return str(default or "").strip()

    normalized_default = str(default or "").strip()
    if normalized_default not in choices:
        normalized_default = choices[0]

    options_str = " ".join(f"{i + 1}.{c}" for i, c in enumerate(choices))
    raw = _prompt_text(f"{label} [{options_str}]", default=normalized_default)
    raw_norm = str(raw or "").strip()

    if raw_norm in choices:
        return raw_norm

    try:
        idx = int(raw_norm)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
    except ValueError:
        pass

    for c in choices:
        if c.lower() == raw_norm.lower():
            return c

    return normalized_default


def _prompt_bool(label: str, *, default: bool) -> bool:
    default_text = "y" if default else "n"
    raw = _prompt_text(f"{label} (y/n)", default=default_text).lower()
    if raw in {"y", "yes", "1", "true", "t"}:
        return True
    if raw in {"n", "no", "0", "false", "f"}:
        return False
    return bool(default)


def _prompt_int(label: str, *, min_val: int, max_val: int, default: int) -> int:
    default = max(min_val, min(int(default or min_val), max_val))
    while True:
        raw = _prompt_text(f"{label} ({min_val}-{max_val})", default=str(default))
        raw = str(raw).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            print(f"  ! 请输入 {min_val}-{max_val} 之间的整数")
            continue
        if value < min_val or value > max_val:
            print(f"  ! 必须在 {min_val}-{max_val} 之间")
            continue
        return value


def _print_welcome_banner(console) -> None:  # noqa: ANN001
    if not _rich_available():
        console.rule("AI 题目生成 · CLI")
        return

    from rich.panel import Panel
    from rich.text import Text

    from backend.core.settings import settings as _settings

    body = Text()
    body.append("AI 题目生成 · 交互模式\n", style="bold cyan")
    body.append(
        f"chat:        {str(_settings.chat_provider or '').strip()}/{str(_settings.main_model or '').strip()}\n"
    )
    if str(getattr(_settings, "lesson_plan_model", "") or "").strip():
        body.append(f"lesson_plan: {str(_settings.lesson_plan_model or '').strip()}\n")
    body.append(f"mcp_search:  {_resolve_cli_mcp_search_model()}\n")

    has_exa = bool((os.getenv("EXA_API_KEY") or "").strip())
    has_zhipu = bool(_settings.zhipu_api_key)
    body.append("MCP keys:    ", style="dim")
    body.append(f"exa={'✓' if has_exa else '×'}  ", style="green" if has_exa else "red")
    body.append(f"zhipu={'✓' if has_zhipu else '×'}", style="green" if has_zhipu else "red")

    console.print(Panel(body, border_style="cyan", padding=(0, 2)))


def _pick_recent_session(console, *, user_id: str) -> str:  # noqa: ANN001
    try:
        sessions = list_saved_sessions(user_id, include_archived=True, limit=5)
    except Exception:  # noqa: BLE001 - session listing is optional prompt sugar.
        logger.warning("question_generate_list_sessions_failed", extra={"user_id": user_id}, exc_info=True)
        sessions = []

    if not sessions:
        return ""

    if _rich_available():
        from rich.table import Table

        table = Table(title=f"最近会话 (user={user_id})", show_lines=False)
        table.add_column("#", justify="right", style="bold cyan", no_wrap=True)
        table.add_column("session_id", no_wrap=True)
        table.add_column("status", no_wrap=True)
        table.add_column("subject", no_wrap=True)
        table.add_column("topic")
        table.add_column("题数", justify="right", no_wrap=True)
        table.add_column("updated_at", no_wrap=True)
        for i, s in enumerate(sessions, start=1):
            drafts = _normalize_draft_questions(s.get("draft_questions"))
            table.add_row(
                str(i),
                str(s.get("session_id") or ""),
                str(s.get("status") or ""),
                str(s.get("subject") or ""),
                str(s.get("topic") or ""),
                str(len(drafts)),
                _fmt_epoch(float(s.get("updated_at_s") or s.get("created_at_s") or 0.0)),
            )
        console.print(table)
    else:
        for i, s in enumerate(sessions, start=1):
            print(f"  {i}. {s.get('session_id')} {s.get('status')} {s.get('subject')}/{s.get('topic')}")

    raw = _prompt_text("加载会话 (输入 #序号 或 session_id, 回车跳过)", default="")
    raw = str(raw or "").strip()
    if not raw:
        return ""

    try:
        idx = int(raw)
        if 1 <= idx <= len(sessions):
            return str(sessions[idx - 1].get("session_id") or "").strip()
    except ValueError:
        pass

    for s in sessions:
        if str(s.get("session_id") or "").strip() == raw:
            return raw

    if _rich_available():
        console.print(f"[yellow]未找到会话: {raw}，将创建新会话[/yellow]")
    else:
        print(f"未找到会话: {raw}，将创建新会话")
    return ""


def _section_header(console, title: str) -> None:  # noqa: ANN001
    if _rich_available():
        from rich.text import Text

        line = Text()
        line.append("\n▶ ", style="bold cyan")
        line.append(title, style="bold")
        console.print(line)
    else:
        print(f"\n--- {title} ---")
