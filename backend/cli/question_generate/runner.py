"""Live-UI state and the async generation runner.

Holds the ``rich.Live`` dashboard (with a no-op fallback) and the
``_run_generation`` coroutine that drives the question_library generation
pipeline while streaming stage/reasoning events into the UI and persisting
snapshots to the preview store.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.generation.question_library.generation import (
    analyze_reference_questions,
    build_source_pack,
    collect_reference_questions,
    enrich_source_pack_with_reference,
    generate_questions,
)
from backend.generation.question_library.preview_store import load_session, save_session
from backend.llm.client import is_llm_configured

from .args import RunParams
from .helpers import _console, _rich_available, logger
from .mcp_tools import _ai_search_materials_via_mcp
from .render import _append_tail, _tail_display
from .session import (
    _append_reasoning_block,
    _draft_identity,
    _ensure_session,
    _materialize_draft,
    _merge_drafts,
    _normalize_draft_questions,
    _save_preview_for_session,
)


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

    # Render-time helpers (stable across refreshes).
    try:
        from backend.core.settings import settings as _settings

        llm_label = f"{str(_settings.chat_provider or '').strip()}/{str(_settings.main_model or '').strip()}".strip("/")
        llm_base_url = str(getattr(_settings, "chat_base_url", "") or "").strip()
    except (ImportError, AttributeError):
        llm_label = ""
        llm_base_url = ""

    def render():
        # Keep a stable fixed-layout "board" so the terminal doesn't scroll.
        size = getattr(console, "size", None)
        width = int(getattr(size, "width", 100) or 100)
        height = int(getattr(size, "height", 30) or 30)

        # Outer Panel has borders; keep a little safety margin.
        inner_width = max(20, width - 4)
        inner_height = max(12, height - 2)

        # Make top/middle sections shrink on small terminals so bottom remains usable.
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
        board = Panel(layout, title=title, border_style="cyan", padding=(0, 1))
        return board

    live = Live(render(), console=console, refresh_per_second=8, transient=False)

    def update_live() -> None:
        live.update(render())

    live._tui_update = update_live  # type: ignore[attr-defined]
    return live


def _tui_update(live) -> None:  # noqa: ANN001
    update_fn = getattr(live, "_tui_update", None)
    if callable(update_fn):
        update_fn()


async def _run_generation(params: RunParams) -> dict:
    console = _console()

    if not is_llm_configured():
        console.print("错误: 未配置 LLM（请检查 .env / config/model.json）。")
        raise SystemExit(2)

    session = _ensure_session(
        session_id=params.session_id,
        user_id=params.user_id,
        preview_id=params.preview_id,
        subject=params.subject,
        topic=params.topic,
        difficulty=params.difficulty,
        question_type=params.question_type,
        mode=params.mode,
        count=params.count,
        use_reference_questions=params.use_reference_questions,
        reference_source=params.reference_source,
        reference_year_range=params.reference_year_range,
        stream_reasoning=params.stream_reasoning,
        use_mcp_search=params.use_mcp_search,
        mcp_search_provider=params.mcp_search_provider,
        mcp_search_mode=params.mcp_search_mode,
        mcp_search_recency_days=params.mcp_search_recency_days,
        mcp_search_limit=params.mcp_search_limit,
        mcp_search_query=params.mcp_search_query,
    )
    session["status"] = "running"
    session = save_session(session)
    _save_preview_for_session(session, preview_status="running")

    ui_state = _UiState(session_id=params.session_id)
    ui_state.batch_index = 0
    ui_state.draft_count = len(_normalize_draft_questions(session.get("draft_questions")))

    # Seed identity map so regenerated drafts keep stable IDs.
    progress_drafts = _normalize_draft_questions(session.get("draft_questions"))
    draft_key_to_id: Dict[str, str] = {}
    for draft in progress_drafts:
        qid = str((draft or {}).get("question_id") or "").strip()
        key = _draft_identity(draft)
        if qid and key:
            draft_key_to_id[key] = qid

    stop_requested = False

    live = _run_live(console, ui_state)

    async def persist_snapshot(*, status: str, drafts: Optional[List[dict]] = None) -> List[dict]:
        nonlocal progress_drafts
        materialized: List[dict] = []
        for item in drafts or []:
            normalized = _materialize_draft(item, draft_key_to_id=draft_key_to_id)
            if normalized is not None:
                materialized.append(normalized)
        if materialized:
            progress_drafts = _merge_drafts(progress_drafts, materialized)

        current = load_session(params.session_id) or {}
        next_session = dict(current)
        next_session.update(
            {
                "session_id": params.session_id,
                "user_id": params.user_id,
                "preview_id": params.preview_id,
                "status": status,
                "mode": params.mode,
                "subject": params.subject,
                "topic": params.topic,
                "difficulty": params.difficulty,
                "question_type": params.question_type,
                "count": params.count,
                "use_reference_questions": params.use_reference_questions,
                "reference_source": params.reference_source,
                "reference_year_range": params.reference_year_range,
                "stream_reasoning": params.stream_reasoning,
                "use_mcp_search": params.use_mcp_search,
                "mcp_search_provider": params.mcp_search_provider,
                "mcp_search_mode": params.mcp_search_mode,
                "mcp_search_recency_days": int(params.mcp_search_recency_days or 0) or 180,
                "mcp_search_limit": params.mcp_search_limit,
                "mcp_search_query": params.mcp_search_query,
                "draft_questions": progress_drafts,
                "stop_requested": bool(next_session.get("stop_requested")) or bool(stop_requested),
            }
        )
        saved = save_session(next_session)
        _save_preview_for_session(saved, preview_status=status)
        ui_state.draft_count = len(progress_drafts)
        _tui_update(live)
        return progress_drafts

    async def run_one_batch(*, batch_index: int) -> List[dict]:
        ui_state.batch_index = batch_index
        ui_state.stage_id = ""
        ui_state.stage_label = ""
        ui_state.stage_progress = 0.0
        ui_state.overall_progress = 0.0
        ui_state.stats = {}
        _tui_update(live)

        last_stage_id = ""

        async def on_stage_event(event: dict) -> None:
            if not isinstance(event, dict):
                return
            phase = str(event.get("phase") or "").strip()
            label = str(event.get("label") or "").strip()
            try:
                progress = float(event.get("progress") or 0.0)
            except (TypeError, ValueError):
                progress = 0.0
            stats = event.get("stats") if isinstance(event.get("stats"), dict) else {}
            nonlocal last_stage_id
            if phase and phase != last_stage_id:
                last_stage_id = phase
                if isinstance(stats, dict) and stats:
                    short_keys = [
                        "kept_specs",
                        "spec_count",
                        "draft_count",
                        "evaluated",
                        "accepted",
                        "rejected",
                        "pass_rate",
                        "final_count",
                    ]
                    short_stats = {k: stats.get(k) for k in short_keys if k in stats}
                    msg = f"[stage] {label or phase} ({phase})"
                    if short_stats:
                        msg += " " + json.dumps(short_stats, ensure_ascii=False)
                    _append_reasoning_entry(ui_state, msg)
                else:
                    _append_reasoning_entry(ui_state, f"[stage] {label or phase} ({phase})")
            ui_state.stage_id = phase
            ui_state.stage_label = label
            ui_state.overall_progress = progress
            ui_state.stage_progress = progress
            ui_state.stats = dict(stats or {})
            if phase == "judge" and isinstance(stats, dict):
                ui_state.accepted = int(stats.get("accepted") or ui_state.accepted or 0)
            _tui_update(live)

        async def on_reasoning_event(event: dict) -> None:
            if not isinstance(event, dict):
                return
            event_type = str(event.get("type") or "").strip() or "reasoning_delta"
            stage_id = str(event.get("stage_id") or "").strip()
            stage_label = str(event.get("stage_label") or "").strip()
            source = str(event.get("source") or "").strip() or "trace"
            content = str(event.get("content") or "")
            message = str(event.get("message") or "").strip()

            if event_type == "reasoning_delta":
                if content:
                    if source == "raw":
                        ui_state.raw_tail = (ui_state.raw_tail + content)[-12000:]
                    else:
                        _append_reasoning_entry(ui_state, content)
                    _tui_update(live)
                    current = load_session(params.session_id)
                    if isinstance(current, dict):
                        _append_reasoning_block(
                            current, stage_id=stage_id, stage_label=stage_label, source=source, content=content
                        )
            elif event_type == "reasoning_status":
                if message:
                    _append_reasoning_entry(ui_state, message)
                    _tui_update(live)
            else:
                if message:
                    _append_reasoning_entry(ui_state, f"[{event_type}] {message}")
                    _tui_update(live)

        async def on_candidate_accepted(candidate: dict) -> None:
            candidate_with_meta = dict(candidate) if isinstance(candidate, dict) else {}
            if params.difficulty and not str(candidate_with_meta.get("difficulty") or "").strip():
                candidate_with_meta["difficulty"] = params.difficulty
            await persist_snapshot(status="running", drafts=[candidate_with_meta])

        async def on_generation_snapshot(snapshot: dict) -> None:
            if not isinstance(snapshot, dict):
                return
            accepted = snapshot.get("accepted")
            raw_items = snapshot.get("raw_candidates")
            if isinstance(accepted, list) and accepted:
                item = accepted[0] if accepted else None
                item_with_meta = dict(item) if isinstance(item, dict) else {}
                if params.difficulty and not str(item_with_meta.get("difficulty") or "").strip():
                    item_with_meta["difficulty"] = params.difficulty
                await persist_snapshot(status="running", drafts=[item_with_meta])
            elif isinstance(raw_items, list) and raw_items:
                item = raw_items[0] if raw_items else None
                item_with_meta = dict(item) if isinstance(item, dict) else {}
                if params.difficulty and not str(item_with_meta.get("difficulty") or "").strip():
                    item_with_meta["difficulty"] = params.difficulty
                await persist_snapshot(status="running", drafts=[item_with_meta])

        # Build source_pack and optional reference enrichment (mirrors API behavior).
        ui_state.stage_id = "source_pack"
        ui_state.stage_label = "素材整理"
        ui_state.stage_progress = 5.0
        ui_state.overall_progress = 5.0
        _append_reasoning_entry(ui_state, "[tool] build_source_pack")
        _tui_update(live)

        study_markdown = ""
        if params.use_mcp_search:
            # Optional: let the LLM call MCP web search (tool calling) and turn results into study_markdown.
            ui_state.stage_id = "mcp_search"
            ui_state.stage_label = "MCP 搜索"
            ui_state.stage_progress = 3.0
            ui_state.overall_progress = 3.0
            _append_reasoning_entry(ui_state, "[tool] ai_mcp_search_materials (tool calling)")
            _tui_update(live)

            def _log_tool(msg: str) -> None:
                _append_reasoning_entry(ui_state, msg)
                _tui_update(live)

            try:
                search_out = await _ai_search_materials_via_mcp(
                    subject=params.subject,
                    topic=params.topic,
                    difficulty=params.difficulty,
                    question_type=params.question_type,
                    query=str(params.mcp_search_query or "").strip(),
                    provider=str(params.mcp_search_provider or "auto").strip(),
                    mode=str(params.mcp_search_mode or "trending").strip(),
                    recency_days=int(params.mcp_search_recency_days or 180),
                    limit=int(params.mcp_search_limit or 5),
                    ui_log_tool=_log_tool,
                )
            except Exception as exc:
                logger.warning("question_generate_mcp_search_materials_failed", exc_info=True)
                search_out = {"success": False, "error": str(exc)}

            study_markdown = str((search_out or {}).get("study_markdown") or "").strip()
            if study_markdown:
                _append_reasoning_entry(ui_state, "[tool] ai_mcp_search_materials ok")
            else:
                err = str((search_out or {}).get("error") or "mcp_search_failed")
                _append_reasoning_entry(ui_state, f"[tool] ai_mcp_search_materials failed: {err}")
            _tui_update(live)

            current = load_session(params.session_id)
            if isinstance(current, dict):
                current = dict(current)
                current["mcp_search"] = {
                    "success": bool((search_out or {}).get("success")),
                    "query": str((search_out or {}).get("query") or "").strip(),
                    "mode": str(params.mcp_search_mode or "").strip() or "trending",
                    "recency_days": int(params.mcp_search_recency_days or 0) or 180,
                    "limit": int(params.mcp_search_limit or 5),
                    "provider": str(params.mcp_search_provider or "auto").strip(),
                    "model": str((search_out or {}).get("model") or "").strip(),
                    "tool_results": (search_out or {}).get("tool_results") if isinstance((search_out or {}).get("tool_results"), list) else [],
                }
                save_session(current)

            # Restore stage label for source pack.
            ui_state.stage_id = "source_pack"
            ui_state.stage_label = "素材整理"
            ui_state.stage_progress = 5.0
            ui_state.overall_progress = 5.0
            _tui_update(live)

        source_pack = await build_source_pack(
            study_markdown,
            params.subject,
            params.topic,
            stream_reasoning=params.stream_reasoning,
            on_reasoning_event=on_reasoning_event,
        )
        ui_state.stats = {
            "facts": len(source_pack.get("facts") or []),
            "skills": len(source_pack.get("skills") or []),
            "forbidden_patterns": len(source_pack.get("forbidden_patterns") or []),
        }
        _tui_update(live)

        reference_questions: List[dict] = []
        reference_analysis: dict = {}
        reference_status: dict = {
            "enabled": bool(params.use_reference_questions),
            "cache_hit": False,
            "degraded": False,
            "fallback_used": "",
            "result_source": "",
            "error": "",
            "count": 0,
        }

        if params.use_reference_questions:
            _append_reasoning_entry(ui_state, "[tool] collect_reference_questions (reference_crawl)")
            ui_state.stage_id = "reference_crawl"
            ui_state.stage_label = "参考题爬取"
            ui_state.stage_progress = 10.0
            ui_state.overall_progress = 10.0
            _tui_update(live)

            ref_result = await collect_reference_questions(
                user_id=params.user_id,
                subject=params.subject,
                topic=params.topic,
                difficulty=params.difficulty,
                question_type=params.question_type,
                knowledge_point_ids=None,
                knowledge_points=[params.topic],
                desired_count=max(5, min(10, params.count + 3)),
                reference_source=params.reference_source,
                reference_year_range=params.reference_year_range,
            )
            if isinstance(ref_result, dict):
                reference_questions = [dict(x) for x in (ref_result.get("questions") or []) if isinstance(x, dict)]
                reference_status.update(
                    {
                        "cache_hit": bool(ref_result.get("cache_hit")),
                        "degraded": bool(ref_result.get("degraded")),
                        "fallback_used": str(ref_result.get("fallback_used") or "").strip(),
                        "result_source": str(ref_result.get("source") or "").strip(),
                        "error": str(ref_result.get("error") or "").strip(),
                        "count": len(reference_questions),
                    }
                )
            ui_state.stats = {"reference_count": len(reference_questions), "cache_hit": reference_status.get("cache_hit")}
            _tui_update(live)

            _append_reasoning_entry(ui_state, "[tool] analyze_reference_questions (reference_analysis)")
            ui_state.stage_id = "reference_analysis"
            ui_state.stage_label = "参考题分析"
            ui_state.stage_progress = 16.0
            ui_state.overall_progress = 16.0
            _tui_update(live)

            if reference_questions:
                reference_analysis = await analyze_reference_questions(
                    subject=params.subject,
                    topic=params.topic,
                    difficulty=params.difficulty,
                    question_type=params.question_type,
                    reference_questions=reference_questions,
                    stream_reasoning=params.stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                source_pack = enrich_source_pack_with_reference(source_pack, reference_analysis, reference_questions)
                ui_state.stats = {
                    "reference_count": len(reference_questions),
                    "question_patterns": len(reference_analysis.get("question_patterns") or [])
                    if isinstance(reference_analysis, dict)
                    else 0,
                }
                _tui_update(live)
            else:
                reference_analysis = {}
                ui_state.stats = {"reference_count": 0, "skipped": True}
                _tui_update(live)

            current = load_session(params.session_id)
            if isinstance(current, dict):
                current = dict(current)
                current["reference_status"] = dict(reference_status)
                current["reference_questions"] = reference_questions[:10]
                current["reference_analysis"] = reference_analysis if isinstance(reference_analysis, dict) else {}
                save_session(current)

        ui_state.stage_id = "spec_search"
        ui_state.stage_label = "规格搜索"
        ui_state.stage_progress = 20.0
        ui_state.overall_progress = 20.0
        _append_reasoning_entry(ui_state, "[tool] generate_questions")
        _tui_update(live)

        finals = await generate_questions(
            source_pack=source_pack,
            count=params.count,
            difficulty=params.difficulty,
            question_type=params.question_type,
            on_stage_event=on_stage_event,
            on_reasoning_event=on_reasoning_event,
            on_candidate_accepted=on_candidate_accepted,
            on_generation_snapshot=on_generation_snapshot,
            stream_reasoning=params.stream_reasoning,
            config=None,
        )

        drafts: List[dict] = []
        for q in finals[: params.count]:
            if not isinstance(q, dict):
                continue
            q_with_meta = dict(q)
            if params.difficulty and not str(q_with_meta.get("difficulty") or "").strip():
                q_with_meta["difficulty"] = params.difficulty
            normalized = _materialize_draft(q_with_meta, draft_key_to_id=draft_key_to_id)
            if normalized is not None:
                drafts.append(normalized)

        if drafts:
            snapshot_status = "running" if params.mode == "infinite" else "pending_review"
            await persist_snapshot(status=snapshot_status, drafts=drafts)
        return drafts

    with live:
        batch_index = 0
        try:
            while True:
                if stop_requested:
                    break
                batch_index += 1
                _append_reasoning_entry(ui_state, f"[batch] start {batch_index} (mode={params.mode})")
                new_drafts = await run_one_batch(batch_index=batch_index)
                ui_state.draft_count = len(
                    _normalize_draft_questions((load_session(params.session_id) or {}).get("draft_questions"))
                )
                _tui_update(live)
                _append_reasoning_entry(
                    ui_state,
                    f"[batch] done {batch_index}: +{len(new_drafts)} drafts, total={ui_state.draft_count}",
                )
                _tui_update(live)

                if params.mode != "infinite":
                    break
                if stop_requested:
                    break
                await asyncio.sleep(0.2)
        except (KeyboardInterrupt, asyncio.CancelledError):
            stop_requested = True
            _append_reasoning_entry(ui_state, "[ctrl+c] interrupted")
            _tui_update(live)
        finally:
            current = load_session(params.session_id)
            if isinstance(current, dict):
                current = dict(current)
                current["stop_requested"] = bool(current.get("stop_requested")) or bool(stop_requested)
                if stop_requested:
                    # If we were interrupted mid-flight, don't leave the session stuck at "running".
                    status_now = str(current.get("status") or "").strip() or "running"
                    if params.mode == "infinite":
                        current["status"] = "stopped"
                    elif status_now == "running":
                        drafts_now = _normalize_draft_questions(current.get("draft_questions"))
                        current["status"] = "pending_review" if drafts_now else "stopped"
                save_session(current)
                _save_preview_for_session(current, preview_status=str(current.get("status") or "pending_review"))

    return load_session(params.session_id) or session
