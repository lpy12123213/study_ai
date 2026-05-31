"""Interactive review, commit, export, session listing and params summary.

These are the post-generation commands wired into argparse subcommands by
:mod:`backend.cli.question_generate.app`.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import List

from backend.api.question_evaluate import evaluate_generated_question_review
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.database.repositories.question.question_library import upsert_question_library_items
from backend.generation.question_library.preview_store import (
    list_sessions as list_saved_sessions,
)
from backend.generation.question_library.preview_store import (
    load_session,
    save_session,
)

from .args import RunParams
from .helpers import (
    _console,
    _fmt_epoch,
    _normalize_review_status,
    _now_stamp,
    _output_dir,
    _resolve_cli_mcp_search_model,
    _rich_available,
    logger,
)
from .prompts import _prompt_text
from .render import _render_question_panel, _render_questions_summary
from .session import _normalize_draft_questions, _save_preview_for_session


def _review_session(*, user_id: str, session_id: str) -> dict:
    console = _console()
    session = load_session(session_id)
    if not isinstance(session, dict) or str(session.get("user_id") or "").strip() != user_id:
        console.print("错误: session_not_found")
        raise SystemExit(2)

    drafts = _normalize_draft_questions(session.get("draft_questions"))
    if not drafts:
        console.print("当前会话没有可审查的题目。")
        return session

    _render_questions_summary(console, drafts)

    confirmed_ids: List[str] = (
        list(session.get("confirmed_question_ids") or []) if isinstance(session.get("confirmed_question_ids"), list) else []
    )
    confirmed_set = {str(x or "").strip() for x in confirmed_ids if str(x or "").strip()}

    idx = 0
    while idx < len(drafts):
        q = dict(drafts[idx])
        _render_question_panel(console, q, index=idx + 1)

        action = _prompt_text("操作 [a]通过 [r]打回 [s]跳过 [A]全部通过 [C]确认通过 [q]退出", default="s")
        action = str(action or "").strip()

        if action.lower() == "q":
            break

        if action == "s":
            idx += 1
            continue

        if action == "r":
            q["keep"] = False
            q["review_status"] = "rejected"
            q["review"] = None
            drafts[idx] = q
            idx += 1
        elif action == "a":
            console.rule("AI 审查中…")
            try:
                review = asyncio.run(
                    evaluate_generated_question_review(
                        subject=str(session.get("subject") or "").strip(),
                        stem=str(q.get("stem") or "").strip(),
                        answer=str(q.get("answer") or "").strip(),
                        analysis=str(q.get("analysis") or "").strip(),
                        requirements="",
                        model="",
                    )
                )
            except Exception as exc:
                logger.warning("question_generate_review_failed", exc_info=True)
                review = {"error": str(exc)}
            q["keep"] = True
            q["review_status"] = "approved"
            q["review"] = review if isinstance(review, dict) else {"raw": review}
            drafts[idx] = q
            # Show a short summary.
            if isinstance(q.get("review"), dict):
                console.print(
                    f"review: verdict={q['review'].get('verdict')} score={q['review'].get('overall_score')} model={q['review'].get('model')}"
                )
            idx += 1
        elif action == "A":
            for j in range(idx, len(drafts)):
                item = dict(drafts[j])
                if _normalize_review_status(item.get("review_status")) in {"rejected", "committed"}:
                    continue
                console.rule(f"AI 审查 {j + 1}/{len(drafts)}…")
                try:
                    review = asyncio.run(
                        evaluate_generated_question_review(
                            subject=str(session.get("subject") or "").strip(),
                            stem=str(item.get("stem") or "").strip(),
                            answer=str(item.get("answer") or "").strip(),
                            analysis=str(item.get("analysis") or "").strip(),
                            requirements="",
                            model="",
                        )
                    )
                except Exception as exc:
                    logger.warning("question_generate_review_failed", exc_info=True)
                    review = {"error": str(exc)}
                item["keep"] = True
                item["review_status"] = "approved"
                item["review"] = review if isinstance(review, dict) else {"raw": review}
                drafts[j] = item
            idx = len(drafts)
        elif action == "C":
            for j, item in enumerate(drafts):
                status = _normalize_review_status(item.get("review_status"))
                if status == "approved" and bool(item.get("keep", True)):
                    qid = str(item.get("question_id") or "").strip()
                    if qid:
                        confirmed_set.add(qid)
                    next_item = dict(item)
                    next_item["review_status"] = "confirmed"
                    drafts[j] = next_item
            idx += 1
        else:
            console.print("未知操作，已跳过。")
            idx += 1

        next_session = dict(session)
        next_session["draft_questions"] = drafts
        next_session["confirmed_question_ids"] = sorted([x for x in confirmed_set if x])
        next_session["status"] = str(next_session.get("status") or "pending_review")
        session = save_session(next_session)
        _save_preview_for_session(session, preview_status=str(session.get("status") or "pending_review"))

    console.print(f"审查结束。confirmed={len(confirmed_set)}，drafts={len(drafts)}。")
    return load_session(session_id) or session


async def _commit_confirmed(*, user_id: str, session_id: str) -> None:
    console = _console()
    session = load_session(session_id)
    if not isinstance(session, dict) or str(session.get("user_id") or "").strip() != user_id:
        console.print("错误: session_not_found")
        raise SystemExit(2)

    subject = str(session.get("subject") or "").strip()
    topic = str(session.get("topic") or "").strip()
    difficulty = str(session.get("difficulty") or "").strip()
    question_type = str(session.get("question_type") or "").strip()

    drafts = _normalize_draft_questions(session.get("draft_questions"))
    confirmed_ids = (
        list(session.get("confirmed_question_ids") or []) if isinstance(session.get("confirmed_question_ids"), list) else []
    )
    confirmed_set = {str(x or "").strip() for x in confirmed_ids if str(x or "").strip()}

    accepted_payload: List[dict] = []
    inserted_ids: List[str] = []
    for q in drafts:
        qid = str(q.get("question_id") or "").strip()
        if not qid or qid not in confirmed_set:
            continue
        if not bool(q.get("keep", True)):
            continue
        status = _normalize_review_status(q.get("review_status"))
        if status not in {"confirmed", "approved"}:
            continue
        stem = str(q.get("stem") or "").strip()
        answer = str(q.get("answer") or "").strip()
        analysis = str(q.get("analysis") or "").strip()
        if not stem or not answer or not analysis:
            continue
        inserted_ids.append(qid)
        accepted_payload.append(
            {
                "question_id": qid,
                "subject": subject,
                "question_type": question_type,
                "difficulty": difficulty,
                "knowledge_point": topic,
                "source_url": "",
                "stem": stem,
                "answer": answer,
                "analysis": analysis,
            }
        )

    if not accepted_payload:
        console.print("没有可入库的题（需要 confirmed 且 keep=true）。")
        return

    await upsert_question_cache(accepted_payload)
    await upsert_question_library_items(
        user_id=user_id,
        items=[{"question_id": qid, "subject": subject, "origin": "ai"} for qid in inserted_ids],
    )

    committed_set = set(inserted_ids)
    updated: List[dict] = []
    for q in drafts:
        next_item = dict(q)
        qid = str(next_item.get("question_id") or "").strip()
        if qid in committed_set:
            next_item["review_status"] = "committed"
        updated.append(next_item)

    session = dict(session)
    session["status"] = "committed"
    session["committed_at_s"] = time.time()
    session["committed_question_ids"] = inserted_ids
    session["draft_questions"] = updated
    save_session(session)
    _save_preview_for_session(session, preview_status="committed")

    console.print(f"入库完成: inserted={len(inserted_ids)}，session_id={session_id}")


async def _export_markdown(*, user_id: str, session_id: str, path: str) -> Path:
    console = _console()
    session = load_session(session_id)
    if not isinstance(session, dict) or str(session.get("user_id") or "").strip() != user_id:
        console.print("错误: session_not_found")
        raise SystemExit(2)

    drafts = _normalize_draft_questions(session.get("draft_questions"))
    if not drafts:
        console.print("没有可导出的题目。")
        raise SystemExit(2)

    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = Path(path).expanduser().resolve() if path else out_dir / f"question_generate_{session_id}_{_now_stamp()}.md"

    lines: List[str] = []
    lines.append("# AI 出题导出\n\n")
    lines.append(f"- session_id: `{session_id}`\n")
    lines.append(f"- subject: {str(session.get('subject') or '').strip()}\n")
    lines.append(f"- topic: {str(session.get('topic') or '').strip()}\n")
    lines.append(f"- exported_at: {_fmt_epoch(time.time())}\n")
    lines.append("\n---\n\n")

    for i, q in enumerate(drafts, start=1):
        qid = str(q.get("question_id") or "").strip()
        status = _normalize_review_status(q.get("review_status"))
        keep = bool(q.get("keep", True))
        lines.append(f"## {i}. {qid}\n\n")
        lines.append(f"- status: `{status}`\n")
        lines.append(f"- keep: `{str(keep).lower()}`\n\n")
        lines.append("### 题干\n\n")
        lines.append(str(q.get("stem") or "").strip() + "\n\n")
        lines.append("### 答案\n\n")
        lines.append(str(q.get("answer") or "").strip() + "\n\n")
        lines.append("### 解析\n\n")
        lines.append(str(q.get("analysis") or "").strip() + "\n\n")
        lines.append("---\n\n")

    resolved.write_text("".join(lines), encoding="utf-8")
    console.print(f"导出完成: {resolved} (count={len(drafts)})")
    return resolved


def _list_sessions_cmd(*, user_id: str, limit: int) -> None:
    console = _console()
    sessions = list_saved_sessions(user_id, include_archived=True, limit=max(1, min(int(limit or 60), 200)))
    if not sessions:
        console.print("暂无会话。")
        return

    if _rich_available():
        from rich.table import Table

        table = Table(title="历史会话", show_lines=False)
        table.add_column("session_id")
        table.add_column("status")
        table.add_column("mode")
        table.add_column("subject")
        table.add_column("topic")
        table.add_column("count", justify="right")
        table.add_column("updated_at")
        for s in sessions:
            drafts = _normalize_draft_questions(s.get("draft_questions"))
            table.add_row(
                str(s.get("session_id") or ""),
                str(s.get("status") or ""),
                str(s.get("mode") or ""),
                str(s.get("subject") or ""),
                str(s.get("topic") or ""),
                str(len(drafts)),
                _fmt_epoch(float(s.get("updated_at_s") or s.get("created_at_s") or 0.0)),
            )
        console.print(table)
        return

    for s in sessions:
        sid = str(s.get("session_id") or "")
        status = str(s.get("status") or "")
        subject = str(s.get("subject") or "")
        topic = str(s.get("topic") or "")
        updated = _fmt_epoch(float(s.get("updated_at_s") or s.get("created_at_s") or 0.0))
        print(sid, status, subject, topic, updated)


def _print_params_summary(console, params: RunParams) -> None:  # noqa: ANN001
    from backend.core.settings import settings

    mcp_search_model = _resolve_cli_mcp_search_model()

    if not _rich_available():
        console.rule("参数确认")
        console.print(f"chat_provider: {settings.chat_provider}")
        console.print(f"chat_base_url: {settings.chat_base_url}")
        console.print(f"main_model: {settings.main_model}")
        console.print(f"lesson_plan_model: {settings.lesson_plan_model}")
        console.print(f"mcp_search_model: {mcp_search_model}")
        console.print(f"session_id: {params.session_id}")
        console.print(f"preview_id: {params.preview_id}")
        console.print(f"user_id: {params.user_id}")
        console.print(f"subject: {params.subject}")
        console.print(f"topic: {params.topic}")
        console.print(f"difficulty: {params.difficulty}")
        console.print(f"question_type: {params.question_type}")
        console.print(f"count: {params.count}")
        console.print(f"mode: {params.mode}")
        console.print(f"use_reference_questions: {params.use_reference_questions}")
        console.print(f"reference_source: {params.reference_source}")
        console.print(f"reference_year_range: {params.reference_year_range}")
        console.print(f"stream_reasoning: {params.stream_reasoning}")
        console.print(f"use_mcp_search: {params.use_mcp_search}")
        console.print(f"mcp_search_provider: {params.mcp_search_provider}")
        console.print(f"mcp_search_mode: {params.mcp_search_mode}")
        console.print(f"mcp_search_recency_days: {params.mcp_search_recency_days}")
        console.print(f"mcp_search_limit: {params.mcp_search_limit}")
        console.print(f"mcp_search_query: {params.mcp_search_query}")
        console.print(f"恢复会话: python -m backend.cli.question_generate review --session-id {params.session_id}")
        return

    from rich.table import Table

    table = Table(title="参数确认", show_lines=False)
    table.add_column("key")
    table.add_column("value")
    rows = [
        ("chat_provider", settings.chat_provider),
        ("chat_base_url", settings.chat_base_url),
        ("main_model", settings.main_model),
        ("lesson_plan_model", settings.lesson_plan_model),
        ("mcp_search_model", mcp_search_model),
        ("session_id", params.session_id),
        ("preview_id", params.preview_id),
        ("user_id", params.user_id),
        ("subject", params.subject),
        ("topic", params.topic),
        ("difficulty", params.difficulty),
        ("question_type", params.question_type),
        ("count", str(params.count)),
        ("mode", params.mode),
        ("use_reference_questions", str(bool(params.use_reference_questions)).lower()),
        ("reference_source", params.reference_source),
        ("reference_year_range", params.reference_year_range),
        ("stream_reasoning", str(bool(params.stream_reasoning)).lower()),
        ("use_mcp_search", str(bool(params.use_mcp_search)).lower()),
        ("mcp_search_provider", params.mcp_search_provider),
        ("mcp_search_mode", params.mcp_search_mode),
        ("mcp_search_recency_days", str(params.mcp_search_recency_days)),
        ("mcp_search_limit", str(params.mcp_search_limit)),
        ("mcp_search_query", params.mcp_search_query or "(auto)"),
    ]
    for k, v in rows:
        table.add_row(k, str(v))
    console.print(table)
    console.print(f"恢复会话: python -m backend.cli.question_generate review --session-id {params.session_id}")
