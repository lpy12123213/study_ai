"""Async generation runner for the question-generation CLI.

Drives the question_library generation pipeline while streaming
stage/reasoning events into the live UI and persisting snapshots to the preview
store.
"""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional

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
from .helpers import _console, logger
from .live_ui import _append_reasoning_entry, _run_live, _set_stage, _tui_update
from .mcp_tools import _ai_search_materials_via_mcp
from .run_state import _prepare_generation_state
from .session import (
    _append_reasoning_block,
    _materialize_draft,
    _merge_drafts,
    _normalize_draft_questions,
    _save_preview_for_session,
)


async def _run_generation(params: RunParams) -> dict:
    console = _console()

    if not is_llm_configured():
        console.print("错误: 未配置 LLM（请检查 .env / config/model.json）。")
        raise SystemExit(2)

    session, ui_state, progress_drafts, draft_key_to_id = _prepare_generation_state(params)

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
        _set_stage(ui_state, "", "", 0.0)
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
        _set_stage(ui_state, "source_pack", "素材整理", 5.0)
        _append_reasoning_entry(ui_state, "[tool] build_source_pack")
        _tui_update(live)

        study_markdown = ""
        if params.use_mcp_search:
            # Optional: let the LLM call MCP web search (tool calling) and turn results into study_markdown.
            _set_stage(ui_state, "mcp_search", "MCP 搜索", 3.0)
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
            except Exception as exc:  # noqa: BLE001 - MCP material search is optional; fall back to empty materials.
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
            _set_stage(ui_state, "source_pack", "素材整理", 5.0)
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
            _set_stage(ui_state, "reference_crawl", "参考题爬取", 10.0)
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
            _set_stage(ui_state, "reference_analysis", "参考题分析", 16.0)
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

        _set_stage(ui_state, "spec_search", "规格搜索", 20.0)
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
