"""Rich Live dashboard helpers for the question-generation CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from .helpers import _rich_available
from .render import _append_tail, _tail_display


@dataclass
class _UiState:
    session_id: str
    stage_id: str = ""
    stage_label: str = ""
    overall_progress: float = 0.0
    stage_progress: float = 0.0
    stats: Dict[str, Any] = None  # type: ignore[assignment]
    accepted: int = 0
    draft_count: int = 0
    batch_index: int = 0
    raw_tail: str = ""
    trace_tail: str = ""

    def __post_init__(self) -> None:
        if self.stats is None:
            self.stats = {}


class _NullLive:
    def __init__(self, console):  # noqa: ANN001
        self.console = console

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        _ = (exc_type, exc, tb)
        return False

    def update(self, renderable) -> None:  # noqa: ANN001
        _ = renderable

    def refresh(self) -> None:
        return


def _append_reasoning_entry(state: "_UiState", addition: str, *, max_lines: int = 240, max_chars: int = 24000) -> None:
    # In the TUI we treat "reasoning" as a unified console:
    # - raw_tail: streamed model reasoning (best-effort)
    # - trace_tail: stage switches + tool calls + fallback traces
    state.trace_tail = _append_tail(
        state.trace_tail,
        addition,
        max_lines=max_lines,
        max_chars=max_chars,
    )


def _set_stage(state: _UiState, stage_id: str, stage_label: str, progress: float) -> None:
    state.stage_id = stage_id
    state.stage_label = stage_label
    state.stage_progress = progress
    state.overall_progress = progress


def _run_live(console, state: _UiState):  # noqa: ANN001
    if not _rich_available():
        return _NullLive(console)

    from rich.console import Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
    from rich.table import Table
    from rich.text import Text

    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("{task.percentage:>5.1f}%"),
        TimeElapsedColumn(),
        expand=True,
    )
    overall_task = progress.add_task("总进度", total=100.0, completed=0.0)
    stage_task = progress.add_task("阶段", total=100.0, completed=0.0)

    try:
        from backend.core.settings import settings as _settings

        llm_label = f"{str(_settings.chat_provider or '').strip()}/{str(_settings.main_model or '').strip()}".strip("/")
        llm_base_url = str(getattr(_settings, "chat_base_url", "") or "").strip()
    except (ImportError, AttributeError):
        llm_label = ""
        llm_base_url = ""

    def render():
        size = getattr(console, "size", None)
        width = int(getattr(size, "width", 100) or 100)
        height = int(getattr(size, "height", 30) or 30)

        inner_width = max(20, width - 4)
        inner_height = max(12, height - 2)

        header_size = 8
        status_size = 9
        min_bottom = 8
        if inner_height - header_size - status_size < min_bottom:
            need = min_bottom - (inner_height - header_size - status_size)
            status_reducible = max(0, status_size - 4)
            dec = min(need, status_reducible)
            status_size -= dec
            need -= dec
            header_reducible = max(0, header_size - 4)
            dec = min(need, header_reducible)
            header_size -= dec

        bottom_height = max(6, inner_height - header_size - status_size)
        bottom_lines = max(6, bottom_height - 2)

        progress.update(overall_task, completed=float(state.overall_progress or 0.0))
        progress.update(
            stage_task,
            completed=float(state.stage_progress or 0.0),
            description=f"阶段: {state.stage_label or '-'}",
        )

        status_table = Table.grid(padding=(0, 2), expand=True)
        status_table.add_column(justify="right", style="bold cyan", no_wrap=True)
        status_table.add_column(ratio=1)
        status_table.add_row("session", state.session_id)
        status_table.add_row("batch", str(state.batch_index or 0))
        status_table.add_row("stage", f"{state.stage_id or '-'} / {state.stage_label or '-'}")
        if llm_label:
            status_table.add_row("llm", llm_label)
        if llm_base_url:
            status_table.add_row("base_url", llm_base_url)
        status_table.add_row("accepted", str(state.accepted))
        status_table.add_row("drafts", str(state.draft_count))
        if state.stats:
            keys = ["kept_specs", "draft_count", "evaluated", "accepted", "final_count", "pass_rate"]
            shown = {k: state.stats.get(k) for k in keys if k in state.stats}
            if shown:
                status_table.add_row("stats", json.dumps(shown, ensure_ascii=False))

        tips = Text()
        tips.append("Ctrl+C: 终止生成并保存会话\n", style="bold")
        tips.append("Utilities:\n", style="bold")
        tips.append("  python -m backend.cli.question_generate sessions\n")
        tips.append("  python -m backend.cli.question_generate review  --session-id <id>\n")
        tips.append("  python -m backend.cli.question_generate commit  --session-id <id>\n")
        tips.append("  python -m backend.cli.question_generate export  --session-id <id>\n")
        header_table = Table.grid(padding=(0, 2), expand=True)
        header_table.add_column(ratio=2)
        header_table.add_column(ratio=1)
        header_table.add_row(progress, tips)

        raw_text = str(state.raw_tail or "").strip()
        trace_text = str(state.trace_tail or "").strip()
        if raw_text and trace_text:
            col_width = max(20, (inner_width - 3) // 2)
            raw_body = _tail_display(raw_text or "(Reasoning 空)", max_lines=bottom_lines, width=col_width)
            trace_body = _tail_display(trace_text or "(Tools 空)", max_lines=bottom_lines, width=col_width)

            left = Text()
            left.append("Reasoning\n", style="bold")
            left.append(raw_body if raw_body else "(Reasoning 空)")

            right = Text()
            right.append("Tools / Trace\n", style="bold")
            right.append(trace_body if trace_body else "(Tools 空)")

            lanes = Table.grid(padding=(0, 1), expand=True)
            lanes.add_column(ratio=1)
            lanes.add_column(ratio=1)
            lanes.add_row(left, right)
            bottom_table = Group(lanes)
        else:
            console_text = trace_text or raw_text
            console_body = _tail_display(console_text or "(console 空)", max_lines=bottom_lines, width=inner_width)
            console_block = Text()
            console_block.append("Console\n", style="bold")
            console_block.append(console_body if console_body else "(console 空)")
            bottom_table = Group(console_block)

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=header_size),
            Layout(name="status", size=status_size),
            Layout(name="bottom", ratio=1),
        )
        layout["header"].update(header_table)
        layout["status"].update(status_table)
        layout["bottom"].update(bottom_table)

        title = f"AI 出题 · session={state.session_id}"
        return Panel(layout, title=title, border_style="cyan", padding=(0, 1))

    live = Live(render(), console=console, refresh_per_second=8, transient=False)

    def update_live() -> None:
        live.update(render())

    live._tui_update = update_live  # type: ignore[attr-defined]
    return live


def _tui_update(live) -> None:  # noqa: ANN001
    update_fn = getattr(live, "_tui_update", None)
    if callable(update_fn):
        update_fn()
