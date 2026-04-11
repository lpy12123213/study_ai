from __future__ import annotations

import argparse
import asyncio
import json
import os
import textwrap
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.api.question_evaluate import evaluate_generated_question_review
from backend.llm.client import chat_completion, is_llm_configured
from backend.core.settings import LESSON_PLAN_MODEL
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.database.repositories.question.question_library import upsert_question_library_items
from backend.question_library.generation import (
    analyze_reference_questions,
    build_ai_question_id,
    build_source_pack,
    collect_reference_questions,
    enrich_source_pack_with_reference,
    generate_questions,
)
from backend.question_library.preview_store import (
    list_sessions as list_saved_sessions,
    load_session,
    new_preview_id,
    new_session_id,
    save_preview,
    save_session,
)


_REVIEW_STATUSES = {"pending_review", "in_review", "approved", "rejected", "confirmed", "committed"}


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _output_dir() -> Path:
    return (_repo_root() / "output").resolve()


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _normalize_review_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in _REVIEW_STATUSES:
        return raw
    return "pending_review"


def _normalize_draft_questions(input_value: Any) -> List[dict]:
    out: List[dict] = []
    for item in input_value or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if not qid:
            continue
        review = item.get("review") if isinstance(item.get("review"), dict) else None
        difficulty = str(item.get("difficulty") or "").strip()
        judge_score_raw = item.get("judge_score")
        if judge_score_raw is None:
            judge_obj = item.get("judge") if isinstance(item.get("judge"), dict) else None
            if isinstance(judge_obj, dict):
                judge_score_raw = judge_obj.get("overall_score")
        judge_score: Optional[int]
        try:
            judge_score = int(judge_score_raw) if judge_score_raw is not None else None
        except Exception:
            judge_score = None
        out.append(
            {
                "question_id": qid,
                "difficulty": difficulty,
                "judge_score": judge_score,
                "stem": str(item.get("stem") or "").strip(),
                "answer": str(item.get("answer") or "").strip(),
                "analysis": str(item.get("analysis") or "").strip(),
                "keep": bool(item.get("keep", True)),
                "review_status": _normalize_review_status(item.get("review_status")),
                "review": dict(review) if review else None,
            }
        )
    return out


def _find_draft_index(items: List[dict], question_id: str) -> int:
    target_id = str(question_id or "").strip()
    for index, item in enumerate(items):
        if str((item or {}).get("question_id") or "").strip() == target_id:
            return index
    return -1


def _merge_drafts(existing: Any, incoming: Any) -> List[dict]:
    merged = [dict(item) for item in _normalize_draft_questions(existing)]
    for item in _normalize_draft_questions(incoming):
        index = _find_draft_index(merged, str(item.get("question_id") or ""))
        if index >= 0:
            merged[index] = {**merged[index], **item}
        else:
            merged.append(dict(item))
    return merged


def _draft_identity(item: dict) -> str:
    stem = str((item or {}).get("stem") or "").strip()
    answer = str((item or {}).get("answer") or "").strip()
    analysis = str((item or {}).get("analysis") or "").strip()
    return json.dumps({"stem": stem, "answer": answer, "analysis": analysis}, ensure_ascii=False, sort_keys=True)


def _materialize_draft(item: dict, *, draft_key_to_id: Dict[str, str]) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    stem = str(item.get("stem") or "").strip()
    answer = str(item.get("answer") or "").strip()
    analysis = str(item.get("analysis") or "").strip()
    if not stem or not answer or not analysis:
        return None

    key = _draft_identity(item)
    qid = str(item.get("question_id") or "").strip() or draft_key_to_id.get(key) or build_ai_question_id(
        suffix=uuid.uuid4().hex[:8]
    )
    draft_key_to_id[key] = qid
    review = item.get("review") if isinstance(item.get("review"), dict) else None
    difficulty = str(item.get("difficulty") or "").strip()
    judge_score_raw = item.get("judge_score")
    judge_obj = item.get("judge") if isinstance(item.get("judge"), dict) else None
    if judge_score_raw is None and isinstance(judge_obj, dict):
        judge_score_raw = judge_obj.get("overall_score")
    judge_score: Optional[int]
    try:
        judge_score = int(judge_score_raw) if judge_score_raw is not None else None
    except Exception:
        judge_score = None
    return {
        "question_id": qid,
        "difficulty": difficulty,
        "judge_score": judge_score,
        "stem": stem,
        "answer": answer,
        "analysis": analysis,
        "keep": bool(item.get("keep", True)),
        "review_status": _normalize_review_status(item.get("review_status")),
        "review": dict(review) if review else None,
    }


def _ensure_session(
    *,
    session_id: str,
    user_id: str,
    preview_id: str,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    mode: str,
    count: int,
    use_reference_questions: bool,
    reference_source: str,
    reference_year_range: str,
    stream_reasoning: bool,
    use_mcp_search: bool,
    mcp_search_provider: str,
    mcp_search_mode: str,
    mcp_search_recency_days: int,
    mcp_search_limit: int,
    mcp_search_query: str,
) -> dict:
    existing = load_session(session_id) if session_id else None
    session = dict(existing or {})
    session["session_id"] = session_id
    session["user_id"] = user_id
    session["preview_id"] = preview_id
    session["status"] = str(session.get("status") or "pending_review").strip() or "pending_review"
    session["mode"] = str(mode or session.get("mode") or "standard").strip() or "standard"
    session["subject"] = subject
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["question_type"] = question_type
    session["count"] = int(count or 0)
    session["use_reference_questions"] = bool(use_reference_questions)
    session["reference_source"] = str(reference_source or "any").strip() or "any"
    session["reference_year_range"] = str(reference_year_range or "all").strip() or "all"
    session["stream_reasoning"] = bool(stream_reasoning)
    session["use_mcp_search"] = bool(use_mcp_search)
    session["mcp_search_provider"] = str(mcp_search_provider or "").strip() or "auto"
    session["mcp_search_mode"] = str(mcp_search_mode or "").strip() or "trending"
    session["mcp_search_recency_days"] = int(mcp_search_recency_days or 0) or 180
    session["mcp_search_limit"] = int(mcp_search_limit or 5)
    session["mcp_search_query"] = str(mcp_search_query or "").strip()
    session.setdefault("draft_questions", [])
    session.setdefault("confirmed_question_ids", [])
    session.setdefault("reasoning_blocks", [])
    session.setdefault("stop_requested", False)
    return save_session(session)


def _save_preview_for_session(session: dict, *, preview_status: str) -> None:
    if not isinstance(session, dict):
        return
    preview_id = str(session.get("preview_id") or "").strip()
    if not preview_id:
        return
    save_preview(
        {
            "preview_id": preview_id,
            "session_id": str(session.get("session_id") or "").strip(),
            "mode": str(session.get("mode") or "standard").strip() or "standard",
            "status": str(preview_status or "").strip() or "running",
            "user_id": str(session.get("user_id") or "").strip(),
            "task_id": str(session.get("latest_task_id") or "").strip(),
            "subject": str(session.get("subject") or "").strip(),
            "topic": str(session.get("topic") or "").strip(),
            "difficulty": str(session.get("difficulty") or "").strip(),
            "question_type": str(session.get("question_type") or "").strip(),
            "use_reference_questions": bool(session.get("use_reference_questions", True)),
            "reference_source": str(session.get("reference_source") or "any").strip() or "any",
            "reference_year_range": str(session.get("reference_year_range") or "all").strip() or "all",
            "study_markdown": "",
            "draft_questions": _normalize_draft_questions(session.get("draft_questions")),
        }
    )


def _append_reasoning_block(session: dict, *, stage_id: str, stage_label: str, source: str, content: str) -> dict:
    if not isinstance(session, dict):
        return session
    if not content:
        return session

    blocks = (
        list(session.get("reasoning_blocks") or []) if isinstance(session.get("reasoning_blocks"), list) else []
    )
    if (
        blocks
        and isinstance(blocks[-1], dict)
        and str(blocks[-1].get("stage_id") or "").strip() == stage_id
        and str(blocks[-1].get("source") or "").strip() == source
    ):
        blocks[-1]["content"] = str(blocks[-1].get("content") or "").rstrip() + content
    else:
        blocks.append(
            {
                "id": f"reason-{uuid.uuid4().hex[:12]}",
                "task_id": "tui",
                "stage_id": stage_id,
                "stage_label": stage_label,
                "source": source,
                "content": content,
            }
        )

    # Prevent unbounded growth on disk.
    if len(blocks) > 200:
        blocks = blocks[-200:]

    session = dict(session)
    session["reasoning_blocks"] = blocks
    return save_session(session)


def _fmt_epoch(epoch_s: float) -> str:
    try:
        return datetime.fromtimestamp(float(epoch_s)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
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
    except Exception:
        return False


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except Exception:
        return False


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

    raw = _prompt_text(f"{label} 可选: {', '.join(choices)}", default=normalized_default)
    raw_norm = str(raw or "").strip()
    if raw_norm in choices:
        return raw_norm
    return normalized_default


def _prompt_bool(label: str, *, default: bool) -> bool:
    default_text = "y" if default else "n"
    raw = _prompt_text(f"{label} (y/n)", default=default_text).lower()
    if raw in {"y", "yes", "1", "true", "t"}:
        return True
    if raw in {"n", "no", "0", "false", "f"}:
        return False
    return bool(default)


def _append_tail(existing: str, addition: str, *, max_lines: int = 120, max_chars: int = 12000) -> str:
    lines: List[str] = []
    if existing:
        lines.extend(str(existing).splitlines())
    if addition:
        lines.extend(str(addition).splitlines())
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    out = "\n".join(lines).rstrip()
    if max_chars > 0 and len(out) > max_chars:
        out = out[-max_chars:].lstrip()
    return out


def _tail_display(text: str, *, max_lines: int, width: int) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    width = max(20, int(width or 80))
    want_lines = max(6, int(max_lines or 30))

    wrapped: List[str] = []
    for ln in raw.split("\n"):
        if ln == "":
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                ln,
                width=width,
                break_long_words=True,
                replace_whitespace=False,
                drop_whitespace=False,
            )
        )

    if len(wrapped) > want_lines:
        wrapped = wrapped[-want_lines:]
        if wrapped:
            wrapped[0] = "… " + wrapped[0]

    return "\n".join(wrapped).rstrip()


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


def _clip_preview(value: Any, *, max_chars: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            text = repr(value)
    text = str(text or "").strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _indent_block(text: str, *, prefix: str = "    ") -> str:
    raw = str(text or "").strip("\n")
    if not raw:
        return ""
    return "\n".join(prefix + line for line in raw.splitlines())


def _format_tool_call_log(tool_name: str, arguments: Dict[str, Any]) -> str:
    body = _clip_preview(arguments, max_chars=1600)
    return f"[tool_call] {tool_name}\n{_indent_block(body)}"


def _format_tool_result_log(tool_name: str, result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return f"[tool_result] {tool_name}\n{_indent_block(_clip_preview(result, max_chars=1200))}"

    summary: Dict[str, Any] = {}
    for key in (
        "success",
        "provider",
        "query",
        "mode",
        "purpose",
        "result_type",
        "result_repr",
        "stdout",
        "error",
        "detail",
    ):
        if key in result and result.get(key) not in (None, "", [], {}):
            summary[key] = result.get(key)
    if isinstance(result.get("results"), list):
        summary["results_count"] = len(result.get("results") or [])
    body = _clip_preview(summary or result, max_chars=1800)
    return f"[tool_result] {tool_name}\n{_indent_block(body)}"


def _mcp_web_search_tool_spec() -> Dict[str, Any]:
    # OpenAI "tools" schema; used by the LLM to decide when/how to call web search.
    return {
        "type": "function",
        "function": {
            "name": "mcp_web_search",
            "description": "【联网搜索】搜索互联网获取出题素材。返回结构化搜索结果列表（含 url）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词/问题"},
                    "limit": {"type": "integer", "description": "返回条数(1-10)", "default": 5},
                    "provider": {
                        "type": "string",
                        "enum": ["auto", "exa", "bigmodel"],
                        "description": "搜索提供方：auto(优先 exa) | exa | bigmodel",
                        "default": "auto",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["trending", "patterns"],
                        "description": "trending=时兴素材；patterns=真题规律",
                        "default": "trending",
                    },
                    "recency_days": {
                        "type": "integer",
                        "description": "trending 模式下按发布日期近 N 天筛选（仅 exa 生效）",
                        "default": 180,
                    },
                },
                "required": ["query"],
            },
        },
    }


def _python_scientific_compute_tool_spec() -> Dict[str, Any]:
    from backend.mcp.tools.python_scientific_compute import openai_tool_spec

    return openai_tool_spec()


async def _exec_mcp_web_search_tool(
    *,
    query: str,
    limit: int,
    provider: str,
    mode: str,
    recency_days: int,
) -> Dict[str, Any]:
    """Execute our MCP web search tool (Exa preferred, BigModel fallback)."""

    query = str(query or "").strip()
    if not query:
        return {"success": False, "provider": "mcp_web_search", "error": "query 不能为空", "results": []}

    limit = max(1, min(int(limit or 5), 10))
    provider_in = str(provider or "auto").strip().lower() or "auto"
    if provider_in not in {"auto", "exa", "bigmodel"}:
        provider_in = "auto"

    mode_in = str(mode or "trending").strip()
    if mode_in not in {"trending", "patterns"}:
        mode_in = "trending"
    days = max(1, min(int(recency_days or 180), 3650))

    if provider_in == "auto":
        try:
            from backend.mcp.search.exa import EXA_API_KEY as _EXA_API_KEY

            has_exa = bool(str(_EXA_API_KEY or "").strip())
        except Exception:
            has_exa = False
        provider_in = "exa" if has_exa else "bigmodel"

    if provider_in == "exa":
        try:
            from backend.mcp.search.exa import exa_search
        except Exception as exc:
            return {"success": False, "provider": "exa", "query": query, "error": f"import_exa_failed: {exc}", "results": []}

        category: Optional[str] = None
        start_published_date: Optional[str] = None
        end_published_date: Optional[str] = None
        if mode_in == "trending":
            category = "news"
            today = datetime.now().date()
            end_published_date = today.isoformat()
            start_published_date = (today - timedelta(days=days)).isoformat()

        res = await exa_search(
            query=query,
            num_results=limit,
            category=category,
            start_published_date=start_published_date,
            end_published_date=end_published_date,
            include_text=False,
            include_summary=True,
            include_highlights=True,
        )
        if not isinstance(res, dict) or not res.get("success"):
            return {
                "success": False,
                "provider": str((res or {}).get("provider") or "exa"),
                "query": query,
                "error": str((res or {}).get("error") or "exa_search_failed"),
                "results": [],
            }

        results_in = res.get("results") if isinstance(res.get("results"), list) else []
        results_out: List[Dict[str, Any]] = []
        for item in results_in[:limit]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            published = str(item.get("published_date") or "").strip()
            snippet = str(item.get("summary") or "").strip()
            if not snippet:
                highlights = item.get("highlights") if isinstance(item.get("highlights"), list) else []
                snippet = str(highlights[0] if highlights else "").strip()
            if len(snippet) > 800:
                snippet = snippet[:800].rstrip() + "…"
            results_out.append({"title": title, "url": url, "snippet": snippet, "published_date": published})

        return {
            "success": True,
            "provider": str(res.get("provider") or "exa"),
            "query": query,
            "mode": mode_in,
            "recency_days": days,
            "results": results_out,
        }

    try:
        from backend.mcp.search.bigmodel import web_search_with_bigmodel_mcp
    except Exception as exc:
        return {
            "success": False,
            "provider": "bigmodel",
            "query": query,
            "error": f"import_bigmodel_failed: {exc}",
            "results": [],
        }

    res = await web_search_with_bigmodel_mcp(query=query, limit=limit, model="")
    if not isinstance(res, dict) or not res.get("success"):
        return {
            "success": False,
            "provider": str((res or {}).get("provider") or "bigmodel"),
            "query": query,
            "error": str((res or {}).get("error") or "bigmodel_search_failed"),
            "detail": str((res or {}).get("detail") or "")[:2000],
            "results": [],
        }

    results_in = res.get("results") if isinstance(res.get("results"), list) else []
    results_out: List[Dict[str, Any]] = []
    for item in results_in[:limit]:
        if not isinstance(item, dict):
            continue
        results_out.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("snippet") or "").strip(),
            }
        )

    return {
        "success": True,
        "provider": str(res.get("provider") or "zhipu-bigmodel-mcp-web-search"),
        "model": str(res.get("model") or "").strip(),
        "query": query,
        "mode": mode_in,
        "recency_days": days,
        "results": results_out,
    }


async def _exec_python_scientific_compute_tool(
    *,
    code: str,
    purpose: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    from backend.mcp.tools.python_scientific_compute import python_scientific_compute

    return await python_scientific_compute(
        code=str(code or "").strip(),
        purpose=str(purpose or "").strip(),
        timeout_seconds=int(timeout_seconds or 5),
    )


def _fallback_search_markdown(*, query: str, tool_result: Dict[str, Any]) -> str:
    provider = str(tool_result.get("provider") or "").strip()
    parts: List[str] = []
    parts.append("# Web Search (MCP)\n")
    parts.append(f"- query: {str(query or '').strip()}\n")
    if provider:
        parts.append(f"- provider: {provider}\n")
    if str(tool_result.get("mode") or "").strip():
        parts.append(f"- mode: {str(tool_result.get('mode') or '').strip()}\n")
    if tool_result.get("recency_days"):
        parts.append(f"- recency_days: {tool_result.get('recency_days')}\n")
    if str(tool_result.get("model") or "").strip():
        parts.append(f"- model: {str(tool_result.get('model') or '').strip()}\n")
    parts.append("\n")

    results = tool_result.get("results") if isinstance(tool_result.get("results"), list) else []
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        published = str(item.get("published_date") or "").strip()
        line = f"- {title}" if title else "- (no title)"
        if url:
            line += f"\n  {url}"
        if published:
            line += f"\n  published: {published}"
        if snippet:
            line += f"\n  {snippet}"
        parts.append(line + "\n")

    return "\n".join(parts).strip()


def _fallback_material_markdown(*, query: str, tool_results: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    parts.append("# AI Tool Materials\n")
    parts.append(f"- query: {str(query or '').strip()}\n\n")

    for item in tool_results[:12]:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip() or "unknown_tool"
        if tool_name == "mcp_web_search":
            parts.append(f"## {tool_name}\n\n")
            parts.append(_fallback_search_markdown(query=query, tool_result=item) + "\n\n")
            continue

        parts.append(f"## {tool_name}\n\n")
        if str(item.get("purpose") or "").strip():
            parts.append(f"- purpose: {str(item.get('purpose') or '').strip()}\n")
        if str(item.get("result_type") or "").strip():
            parts.append(f"- result_type: {str(item.get('result_type') or '').strip()}\n")
        if str(item.get("result_repr") or "").strip():
            parts.append(f"- result: {str(item.get('result_repr') or '').strip()}\n")
        if str(item.get("stdout") or "").strip():
            parts.append(f"- stdout: {str(item.get('stdout') or '').strip()}\n")
        if str(item.get("error") or "").strip():
            parts.append(f"- error: {str(item.get('error') or '').strip()}\n")
        parts.append("\n")

    return "".join(parts).strip()


async def _ai_search_materials_via_mcp(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    query: str,
    provider: str,
    mode: str,
    recency_days: int,
    limit: int,
    ui_log_tool: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Let the LLM call MCP-style tools to prepare study materials."""

    # This stage relies on tool-calling + citations. Prefer a tool-capable model by default,
    # and allow override via env var. Do NOT silently inherit a cheap/non-tool-capable
    # lesson_plan model here, otherwise we may get hallucinated "sources".
    effective_model = str(os.getenv("QUESTION_LIBRARY_MCP_SEARCH_MODEL") or "").strip() or "openai/gpt-5-mini"

    def _log(msg: str) -> None:
        if callable(ui_log_tool):
            try:
                ui_log_tool(msg)
            except Exception:
                return

    base_query = str(query or "").strip()
    if not base_query:
        tokens = [subject, topic]
        tokens = [str(x or "").strip() for x in tokens if str(x or "").strip()]
        if str(mode or "").strip() == "patterns":
            more = [difficulty, question_type, "真题", "解题思路", "出题规律"]
        else:
            year = datetime.now().year
            more = [str(year), "热点", "时兴", "素材", "案例", "真实数据"]
        more = [str(x or "").strip() for x in more if str(x or "").strip()]
        base_query = " ".join(tokens + more).strip()

    tools = [_mcp_web_search_tool_spec(), _python_scientific_compute_tool_spec()]
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是一个出题素材检索助手。你必须先调用 mcp_web_search 搜索互联网资料，"
                "并可按需调用 python_scientific_compute 做公式验证、数值试算、样例构造或结果核对。"
                "随后输出一段 Markdown，包含：\n"
                "1) 5-10 条可用于出题的素材点/事实点（每条都要附带来源 url；不要编造）\n"
                "2) 如进行了计算，请给出可复用的计算结论或构造结果\n"
                "3) 每条素材点尽量与学科/知识点相关；如果不是直接相关，要说明如何转化为题目背景\n"
                "4) 语言简洁，不要输出与任务无关的解释。\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"学科: {subject}\n"
                f"主题: {topic}\n"
                f"难度: {difficulty}\n"
                f"题型: {question_type}\n"
                f"目标: {mode} (trending=时兴素材, patterns=真题规律)\n"
                f"recency_days: {int(recency_days or 180)}\n"
                f"limit: {int(limit or 5)}\n"
                f"provider: {provider}\n\n"
                f"请先搜索：{base_query}\n"
            ),
        },
    ]

    aggregated_tool_results: List[Dict[str, Any]] = []
    max_iters = 4
    for it in range(max_iters):
        res = await chat_completion(
            messages=messages,  # type: ignore[arg-type]
            model=effective_model,
            temperature=0.2,
            max_tokens=1600,
            tools=tools,
            tool_choice="auto",
            stream=False,
            raise_on_fail=False,
            retries=2,
            req_id_prefix="mcp-search",
        )

        tool_calls = list(res.tool_calls or [])
        if tool_calls:
            messages.append({"role": "assistant", "content": res.content or "", "tool_calls": tool_calls})
            for tc in tool_calls[:3]:
                fn = tc.get("function") if isinstance(tc, dict) else {}
                tool_name = str((fn or {}).get("name") or "").strip()
                tool_id = str(tc.get("id") or "").strip()
                raw_args = (fn or {}).get("arguments") if isinstance(fn, dict) else {}
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}
                else:
                    args = raw_args if isinstance(raw_args, dict) else {}

                _log(_format_tool_call_log(tool_name or "unknown_tool", args))

                if tool_name == "mcp_web_search":
                    tool_query = str(args.get("query") or base_query).strip()
                    tool_limit = int(args.get("limit") or limit or 5)
                    tool_limit = max(1, min(tool_limit, 10))

                    # Respect CLI/user choice over the model's suggestion (prevents accidental provider flips).
                    forced_provider = str(provider or "").strip().lower()
                    if forced_provider in {"exa", "bigmodel"}:
                        tool_provider = forced_provider
                    else:
                        tool_provider = str(args.get("provider") or "auto").strip()

                    forced_mode = str(mode or "").strip()
                    if forced_mode in {"trending", "patterns"}:
                        tool_mode = forced_mode
                    else:
                        tool_mode = str(args.get("mode") or "trending").strip()

                    tool_days = int(recency_days or 180)
                    tool_result = await _exec_mcp_web_search_tool(
                        query=tool_query,
                        limit=tool_limit,
                        provider=tool_provider,
                        mode=tool_mode,
                        recency_days=tool_days,
                    )
                elif tool_name == "python_scientific_compute":
                    tool_result = await _exec_python_scientific_compute_tool(
                        code=str(args.get("code") or "").strip(),
                        purpose=str(args.get("purpose") or "").strip(),
                        timeout_seconds=int(args.get("timeout_seconds") or 5),
                    )
                else:
                    tool_result = {"success": False, "error": f"unsupported_tool: {tool_name}", "provider": "cli"}

                if isinstance(tool_result, dict):
                    tool_result = {"tool_name": tool_name, **tool_result}
                _log(_format_tool_result_log(tool_name or "unknown_tool", tool_result if isinstance(tool_result, dict) else {"raw": tool_result}))

                if tool_id:
                    messages.append(
                        {"role": "tool", "tool_call_id": tool_id, "content": json.dumps(tool_result, ensure_ascii=False)}
                    )
                else:
                    messages.append({"role": "tool", "content": json.dumps(tool_result, ensure_ascii=False)})
                aggregated_tool_results.append(dict(tool_result) if isinstance(tool_result, dict) else {"raw": tool_result})
            continue

        # No tool calls: LLM finished.
        content = str(res.content or "").strip()
        if it == 0 and not aggregated_tool_results:
            # Enforce at least one real search call so the downstream material block can cite URLs.
            forced_args = {
                "query": base_query,
                "limit": int(limit or 5),
                "provider": str(provider or "auto").strip() or "auto",
                "mode": str(mode or "trending").strip() or "trending",
                "recency_days": int(recency_days or 180),
            }
            _log(_format_tool_call_log("mcp_web_search", forced_args))
            tool_result = await _exec_mcp_web_search_tool(
                query=base_query,
                limit=int(limit or 5),
                provider=str(provider or "auto").strip() or "auto",
                mode=str(mode or "trending").strip() or "trending",
                recency_days=int(recency_days or 180),
            )
            tool_payload = {"tool_name": "mcp_web_search", **(tool_result if isinstance(tool_result, dict) else {"raw": tool_result})}
            _log(_format_tool_result_log("mcp_web_search", tool_payload if isinstance(tool_payload, dict) else {"raw": tool_payload}))
            aggregated_tool_results.append(dict(tool_payload) if isinstance(tool_payload, dict) else {"raw": tool_payload})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "下面是 mcp_web_search 的搜索结果（JSON）。请基于这些结果输出所需 Markdown（每条素材点必须附带来源 url；不要编造）。\n\n"
                        f"```json\n{json.dumps(tool_payload, ensure_ascii=False)[:9000]}\n```"
                    ),
                }
            )
            continue
        if not content and aggregated_tool_results:
            content = _fallback_material_markdown(query=base_query, tool_results=aggregated_tool_results)
        return {
            "success": True,
            "query": base_query,
            "provider": provider,
            "mode": mode,
            "recency_days": int(recency_days or 180),
            "limit": int(limit or 5),
            "study_markdown": content,
            "tool_results": aggregated_tool_results[:10],
            "model": effective_model,
        }

    # Max iterations reached. Fallback to the last tool results.
    content = _fallback_material_markdown(query=base_query, tool_results=aggregated_tool_results) if aggregated_tool_results else ""
    return {
        "success": bool(content),
        "query": base_query,
        "provider": provider,
        "mode": mode,
        "recency_days": int(recency_days or 180),
        "limit": int(limit or 5),
        "study_markdown": content,
        "tool_results": aggregated_tool_results[:10],
        "model": effective_model,
        "error": "max_tool_iterations_reached",
    }


@dataclass
class RunParams:
    user_id: str
    session_id: str
    preview_id: str
    subject: str
    topic: str
    difficulty: str
    question_type: str
    count: int
    mode: str  # standard|infinite
    use_reference_questions: bool
    reference_source: str  # any|gaokao|mock|joint
    reference_year_range: str  # all|3|5
    stream_reasoning: bool
    use_mcp_search: bool
    mcp_search_provider: str  # auto|exa|bigmodel
    mcp_search_mode: str  # trending|patterns
    mcp_search_recency_days: int
    mcp_search_limit: int
    mcp_search_query: str


def _resolve_params_from_args(args: argparse.Namespace) -> RunParams:
    user_id = _safe_user_id(str(getattr(args, "user_id", "") or "1"))
    session_id = str(getattr(args, "session_id", "") or "").strip()

    existing: Optional[dict] = load_session(session_id) if session_id else None
    if session_id and existing and str(existing.get("user_id") or "").strip() != user_id:
        raise SystemExit("session_not_found_or_not_owned")

    subject = str(getattr(args, "subject", "") or (existing or {}).get("subject") or "").strip()
    topic = str(getattr(args, "topic", "") or (existing or {}).get("topic") or "").strip()
    difficulty = str(getattr(args, "difficulty", "") or (existing or {}).get("difficulty") or "").strip()
    question_type = str(getattr(args, "question_type", "") or (existing or {}).get("question_type") or "").strip()
    mode = str(getattr(args, "mode", "") or (existing or {}).get("mode") or "standard").strip() or "standard"
    if mode not in {"standard", "infinite"}:
        mode = "standard"

    raw_count = getattr(args, "count", None)
    if raw_count is None:
        count = _as_int((existing or {}).get("count"), 5) or 5
    else:
        count = _as_int(raw_count, _as_int((existing or {}).get("count"), 5) or 5)
    count = max(1, min(int(count or 5), 10))

    use_reference_questions = (
        bool(getattr(args, "use_reference_questions", False))
        if getattr(args, "use_reference_questions", None) is not None
        else bool((existing or {}).get("use_reference_questions", True))
    )
    if getattr(args, "no_reference", False):
        use_reference_questions = False

    reference_source = str(getattr(args, "reference_source", "") or (existing or {}).get("reference_source") or "any").strip() or "any"
    if reference_source not in {"any", "gaokao", "mock", "joint"}:
        reference_source = "any"
    reference_year_range = str(getattr(args, "reference_year_range", "") or (existing or {}).get("reference_year_range") or "all").strip() or "all"
    if reference_year_range not in {"all", "3", "5"}:
        reference_year_range = "all"

    stream_reasoning = bool(getattr(args, "stream_reasoning", False))

    use_mcp_search = bool(getattr(args, "mcp_search", False)) or bool((existing or {}).get("use_mcp_search", False))
    mcp_search_provider = str(
        getattr(args, "mcp_search_provider", "")
        or (existing or {}).get("mcp_search_provider")
        or "auto"
    ).strip()
    if mcp_search_provider not in {"auto", "exa", "bigmodel"}:
        mcp_search_provider = "auto"
    mcp_search_mode = str(getattr(args, "mcp_search_mode", "") or (existing or {}).get("mcp_search_mode") or "trending").strip()
    if mcp_search_mode not in {"trending", "patterns"}:
        mcp_search_mode = "trending"
    mcp_search_recency_days = _as_int(
        getattr(args, "mcp_search_recency_days", 180), _as_int((existing or {}).get("mcp_search_recency_days"), 180)
    )
    mcp_search_recency_days = max(1, min(int(mcp_search_recency_days or 180), 3650))
    mcp_search_limit = _as_int(getattr(args, "mcp_search_limit", 5), _as_int((existing or {}).get("mcp_search_limit"), 5))
    mcp_search_limit = max(1, min(int(mcp_search_limit or 5), 10))
    mcp_search_query = str(getattr(args, "mcp_search_query", "") or (existing or {}).get("mcp_search_query") or "").strip()

    if not session_id:
        session_id = new_session_id()
    preview_id = str((existing or {}).get("preview_id") or "").strip() or new_preview_id()

    if getattr(args, "interactive", False) or not subject or not topic:
        subject = _prompt_text("学科", default=subject or "高中数学").strip()
        topic = _prompt_text("知识点/主题", default=topic or "").strip()
        difficulty = _prompt_choice("难度", ["简单", "中等", "困难"], default=difficulty or "中等")
        question_type = _prompt_text("题型(可留空)", default=question_type or _infer_question_type_from_topic(topic)).strip()
        count = max(1, min(_as_int(_prompt_text("题量(1-10)", default=str(count)), count), 10))
        mode = _prompt_choice("模式", ["standard", "infinite"], default=mode)
        use_reference_questions = _prompt_bool("是否参考真题", default=use_reference_questions)
        if use_reference_questions:
            reference_source = _prompt_choice("参考来源", ["any", "gaokao", "mock", "joint"], default=reference_source)
            reference_year_range = _prompt_choice("参考年份范围", ["all", "3", "5"], default=reference_year_range)
        stream_reasoning = _prompt_bool("是否流式输出 reasoning", default=stream_reasoning)
        default_mcp = use_mcp_search or bool((os.getenv("EXA_API_KEY") or os.getenv("ZHIPU_API_KEY") or "").strip())
        use_mcp_search = _prompt_bool("是否使用 MCP 搜索补充素材", default=default_mcp)
        if use_mcp_search:
            mcp_search_provider = _prompt_choice("MCP 搜索 provider", ["auto", "exa", "bigmodel"], default=mcp_search_provider or "auto")
            mcp_search_mode = _prompt_choice("MCP 搜索模式", ["trending", "patterns"], default=mcp_search_mode or "trending")
            mcp_search_recency_days = max(
                1,
                min(
                    _as_int(_prompt_text("MCP 搜索 recency days(1-3650)", default=str(mcp_search_recency_days)), mcp_search_recency_days),
                    3650,
                ),
            )
            mcp_search_limit = max(1, min(_as_int(_prompt_text("MCP 搜索返回条数(1-10)", default=str(mcp_search_limit)), mcp_search_limit), 10))
            mcp_search_query = _prompt_text("MCP 搜索 query(可留空自动)", default=mcp_search_query).strip()

    if not question_type:
        inferred = _infer_question_type_from_topic(topic)
        if inferred:
            question_type = inferred

    return RunParams(
        user_id=user_id,
        session_id=session_id,
        preview_id=preview_id,
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        count=count,
        mode=mode,
        use_reference_questions=use_reference_questions,
        reference_source=reference_source,
        reference_year_range=reference_year_range,
        stream_reasoning=stream_reasoning,
        use_mcp_search=use_mcp_search,
        mcp_search_provider=mcp_search_provider,
        mcp_search_mode=mcp_search_mode,
        mcp_search_recency_days=int(mcp_search_recency_days or 180),
        mcp_search_limit=mcp_search_limit,
        mcp_search_query=mcp_search_query,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.cli.question_generate", add_help=True)
    subparsers = parser.add_subparsers(dest="cmd")

    def add_common_generate_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--user-id", default="1")
        p.add_argument("--session-id", default="")
        p.add_argument("--subject", default="")
        p.add_argument("--topic", default="")
        p.add_argument("--difficulty", default="")
        p.add_argument("--question-type", default="")
        p.add_argument("--count", type=int, default=None)
        p.add_argument("--mode", default="standard", choices=["standard", "infinite"])
        p.add_argument("--use-reference-questions", action="store_true", default=None)
        p.add_argument("--no-reference", action="store_true", default=False)
        p.add_argument("--reference-source", default="any", choices=["any", "gaokao", "mock", "joint"])
        p.add_argument("--reference-year-range", default="all", choices=["all", "3", "5"])
        p.add_argument("--stream-reasoning", action="store_true", default=False)
        p.add_argument("--mcp-search", action="store_true", default=False)
        p.add_argument(
            "--mcp-search-provider",
            default="auto",
            choices=["auto", "exa", "bigmodel"],
            help="MCP 搜索提供方: auto(优先 exa) | exa | bigmodel",
        )
        p.add_argument(
            "--mcp-search-mode",
            default="trending",
            choices=["trending", "patterns"],
            help="MCP 搜索目的: trending(时兴素材) | patterns(真题规律)",
        )
        p.add_argument("--mcp-search-recency-days", type=int, default=180, help="trending 模式下按发布日期近 N 天筛选")
        p.add_argument("--mcp-search-limit", type=int, default=5)
        p.add_argument("--mcp-search-query", default="")
        p.add_argument("--interactive", action="store_true", default=False)

    gen = subparsers.add_parser("generate", help="生成题目并进入终端审查")
    add_common_generate_args(gen)

    sessions = subparsers.add_parser("sessions", help="列出历史会话")
    sessions.add_argument("--user-id", default="1")
    sessions.add_argument("--limit", type=int, default=60)

    review = subparsers.add_parser("review", help="恢复会话并进入审查模式")
    review.add_argument("--user-id", default="1")
    review.add_argument("--session-id", required=True)

    commit = subparsers.add_parser("commit", help="将 confirmed 的题目批量入库")
    commit.add_argument("--user-id", default="1")
    commit.add_argument("--session-id", required=True)

    export = subparsers.add_parser("export", help="导出会话题目为 Markdown")
    export.add_argument("--user-id", default="1")
    export.add_argument("--session-id", required=True)
    export.add_argument("--path", default="")

    parser.set_defaults(cmd="generate")
    add_common_generate_args(parser)
    return parser


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


def _run_live(console, state: _UiState):  # noqa: ANN001
    if not _rich_available():
        return _NullLive(console)

    from rich.console import Group
    from rich.live import Live
    from rich.layout import Layout
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
    except Exception:
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
            except Exception:
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


def _render_question_panel(console, q: dict, *, index: int) -> None:  # noqa: ANN001
    if not _rich_available():
        print(
            f"[{index}] {q.get('question_id')}\n{q.get('stem')}\n答: {q.get('answer')}\n解: {q.get('analysis')}\n"
        )
        return

    from rich.markdown import Markdown
    from rich.panel import Panel

    stem = str(q.get("stem") or "").strip()
    answer = str(q.get("answer") or "").strip()
    analysis = str(q.get("analysis") or "").strip()
    review_status = str(q.get("review_status") or "").strip()
    difficulty = str(q.get("difficulty") or "").strip()
    judge_score = q.get("judge_score")
    score_text = ""
    if judge_score is not None:
        try:
            score_text = f" score={int(judge_score)}"
        except Exception:
            score_text = f" score={judge_score}"
    diff_text = f" {difficulty}" if difficulty else ""
    title = f"{index}. {str(q.get('question_id') or '').strip()} [{review_status}]{diff_text}{score_text}"
    body_md = f"### 题干\n\n{stem}\n\n### 答案\n\n{answer}\n\n### 解析\n\n{analysis}\n"
    console.print(Panel(Markdown(body_md), title=title, border_style="green" if q.get("keep", True) else "red"))


def _render_questions_summary(console, drafts: List[dict]) -> None:  # noqa: ANN001
    if not _rich_available():
        for i, q in enumerate(drafts, start=1):
            print(i, q.get("question_id"), q.get("review_status"), "keep" if q.get("keep", True) else "drop")
        return

    from rich.table import Table

    table = Table(title="题目摘要", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("question_id")
    table.add_column("status")
    table.add_column("difficulty")
    table.add_column("score", justify="right")
    table.add_column("keep")
    table.add_column("stem_preview")
    for i, q in enumerate(drafts, start=1):
        stem = str(q.get("stem") or "").strip().replace("\n", " ")
        preview = stem[:60] + ("…" if len(stem) > 60 else "")
        table.add_row(
            str(i),
            str(q.get("question_id") or ""),
            str(q.get("review_status") or ""),
            str(q.get("difficulty") or ""),
            "" if q.get("judge_score") is None else str(q.get("judge_score")),
            "yes" if bool(q.get("keep", True)) else "no",
            preview,
        )
    console.print(table)


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

    mcp_search_model = str(os.getenv("QUESTION_LIBRARY_MCP_SEARCH_MODEL") or "").strip() or "openai/gpt-5-mini"

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


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cmd = str(getattr(args, "cmd", "") or "generate").strip()
    if cmd == "sessions":
        _list_sessions_cmd(user_id=_safe_user_id(args.user_id), limit=int(args.limit or 60))
        return

    if cmd == "review":
        _review_session(user_id=_safe_user_id(args.user_id), session_id=str(args.session_id or "").strip())
        return

    if cmd == "commit":
        asyncio.run(_commit_confirmed(user_id=_safe_user_id(args.user_id), session_id=str(args.session_id or "").strip()))
        return

    if cmd == "export":
        asyncio.run(
            _export_markdown(
                user_id=_safe_user_id(args.user_id),
                session_id=str(args.session_id or "").strip(),
                path=str(args.path or "").strip(),
            )
        )
        return

    # generate (default)
    params = _resolve_params_from_args(args)
    _print_params_summary(_console(), params)
    session = asyncio.run(_run_generation(params))
    _review_session(user_id=params.user_id, session_id=str(session.get("session_id") or params.session_id))


if __name__ == "__main__":
    main()
