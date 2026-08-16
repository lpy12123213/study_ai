"""Argument parsing and run-parameter resolution for the CLI.

Holds :class:`RunParams`, the argparse builder, and the resolver that merges
CLI flags, an existing session, and (optionally) interactive prompts into a
single immutable run spec.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Optional

from backend.core.settings import settings
from backend.generation.question_library.preview_store import (
    load_session,
    new_preview_id,
    new_session_id,
)

from .helpers import (
    _as_int,
    _console,
    _infer_question_type_from_topic,
    _rich_available,
    _safe_user_id,
)
from .prompts import (
    _pick_recent_session,
    _print_welcome_banner,
    _prompt_bool,
    _prompt_choice,
    _prompt_int,
    _prompt_text,
    _section_header,
)


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
    mcp_search_provider: str  # auto|tavily|exa|bigmodel
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
    if mcp_search_provider not in {"auto", "tavily", "exa", "bigmodel"}:
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
        console = _console()
        _print_welcome_banner(console)

        if not session_id:
            loaded_sid = _pick_recent_session(console, user_id=user_id)
            if loaded_sid:
                loaded_existing = load_session(loaded_sid)
                if isinstance(loaded_existing, dict) and str(loaded_existing.get("user_id") or "").strip() == user_id:
                    session_id = loaded_sid
                    existing = loaded_existing
                    if _rich_available():
                        console.print(f"[green]✓ 已加载会话:[/green] {loaded_sid}")
                    else:
                        print(f"已加载会话: {loaded_sid}")
                    subject = subject or str(existing.get("subject") or "").strip()
                    topic = topic or str(existing.get("topic") or "").strip()
                    difficulty = difficulty or str(existing.get("difficulty") or "").strip()
                    question_type = question_type or str(existing.get("question_type") or "").strip()
                    mode = str(existing.get("mode") or mode or "standard").strip() or "standard"
                    count = _as_int(existing.get("count"), count) or count
                    use_reference_questions = bool(existing.get("use_reference_questions", use_reference_questions))
                    reference_source = str(existing.get("reference_source") or reference_source or "any").strip() or "any"
                    reference_year_range = str(existing.get("reference_year_range") or reference_year_range or "all").strip() or "all"
                    stream_reasoning = bool(existing.get("stream_reasoning", stream_reasoning))
                    use_mcp_search = bool(existing.get("use_mcp_search", use_mcp_search))
                    mcp_search_provider = str(existing.get("mcp_search_provider") or mcp_search_provider or "auto").strip() or "auto"
                    mcp_search_mode = str(existing.get("mcp_search_mode") or mcp_search_mode or "trending").strip() or "trending"
                    mcp_search_recency_days = _as_int(existing.get("mcp_search_recency_days"), mcp_search_recency_days) or 180
                    mcp_search_limit = _as_int(existing.get("mcp_search_limit"), mcp_search_limit) or 5
                    mcp_search_query = str(existing.get("mcp_search_query") or mcp_search_query or "").strip()
                    preview_id = str(existing.get("preview_id") or "").strip() or preview_id
                else:
                    if _rich_available():
                        console.print(f"[yellow]会话加载失败或不属于当前用户: {loaded_sid}，将创建新会话[/yellow]")
                    else:
                        print(f"会话加载失败或不属于当前用户: {loaded_sid}，将创建新会话")

        _section_header(console, "基本信息")
        subject = _prompt_text("学科", default=subject or "高中数学").strip()
        topic = _prompt_text("知识点/主题", default=topic or "").strip()
        difficulty = _prompt_choice("难度", ["简单", "中等", "困难"], default=difficulty or "中等")
        question_type = _prompt_text(
            "题型 (留空自动推断)",
            default=question_type or _infer_question_type_from_topic(topic),
        ).strip()
        count = _prompt_int("题量", min_val=1, max_val=10, default=count or 5)
        mode = _prompt_choice("模式", ["standard", "infinite"], default=mode or "standard")

        _section_header(console, "参考真题")
        use_reference_questions = _prompt_bool("使用真题作参考", default=use_reference_questions)
        if use_reference_questions:
            reference_source = _prompt_choice(
                "参考来源", ["any", "gaokao", "mock", "joint"], default=reference_source or "any"
            )
            reference_year_range = _prompt_choice(
                "年份范围", ["all", "3", "5"], default=reference_year_range or "all"
            )

        _section_header(console, "高级设置")
        stream_reasoning = _prompt_bool("流式输出 reasoning", default=stream_reasoning)
        default_mcp = use_mcp_search or bool(
            (os.getenv("TAVILY_API_KEY") or os.getenv("EXA_API_KEY") or "").strip()
            or settings.zhipu_api_key
        )
        use_mcp_search = _prompt_bool("MCP 搜索补充素材", default=default_mcp)
        if use_mcp_search:
            mcp_search_provider = _prompt_choice(
                "MCP provider", ["auto", "tavily", "exa", "bigmodel"], default=mcp_search_provider or "auto"
            )
            mcp_search_mode = _prompt_choice(
                "MCP 模式", ["trending", "patterns"], default=mcp_search_mode or "trending"
            )
            mcp_search_recency_days = _prompt_int(
                "MCP recency days", min_val=1, max_val=3650, default=mcp_search_recency_days or 180
            )
            mcp_search_limit = _prompt_int(
                "MCP 返回条数", min_val=1, max_val=10, default=mcp_search_limit or 5
            )
            mcp_search_query = _prompt_text("MCP 搜索 query (留空自动)", default=mcp_search_query).strip()

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
            choices=["auto", "tavily", "exa", "bigmodel"],
            help="MCP 搜索提供方: auto(优先 tavily) | tavily | exa | bigmodel",
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
