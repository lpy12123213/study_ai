"""Batch-import crawled questions into the local question library.

Example:
    python -m backend.cli.question_library_crawl --subject 高中物理 --target 1000 --domains mechanics,electromagnetism
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import delete, select

from backend.database.engine import async_session_maker
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.database.repositories.question.question_library import upsert_question_library_items
from backend.database.schema import QuestionLibraryItem
from backend.generation.question_library.crawl_plan import (
    KeywordPlanItem,
    normalize_domains,
)
from backend.generation.question_library.crawl_plan import (
    build_keyword_plan as _build_shared_plan,
)
from backend.integrations.crawler.zujuan.client import ZujuanCrawler


@dataclass(frozen=True)
class CrawlImportConfig:
    user_id: str = "1"
    subject: str = "高中物理"
    target: int = 1000
    domains: tuple[str, ...] = ("all",)
    difficulty_value_max: float = 0.65
    require_difficulty_value: bool = True
    limit_per_query: int = 120
    max_pages: int = 12
    rounds: int = 3
    concurrency: int = 2
    parse_content: bool = True
    replace_existing: bool = False
    dry_run: bool = False
    log_path: Path = Path(".local/imports/question_library_crawl.jsonl")
    summary_path: Path = Path(".local/imports/question_library_crawl_summary.json")
    custom_keywords: tuple[str, ...] = field(default_factory=tuple)


InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").replace("，", ",").split(",") if part.strip())


def _normalize_domains(values: Iterable[str]) -> tuple[str, ...]:
    try:
        return normalize_domains(values)
    except ValueError as exc:
        # CLI 语义保持不变：非法域直接终止并给出可读错误。
        raise SystemExit(str(exc)) from exc


def build_keyword_plan(config: CrawlImportConfig) -> list[KeywordPlanItem]:
    return _build_shared_plan(custom_keywords=config.custom_keywords, domains=config.domains)


def _difficulty_value_ok(item: dict[str, Any], *, max_value: float, require_value: bool) -> bool:
    raw = item.get("difficulty_value")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return not require_value
    return value <= float(max_value)


def _quality_flags(item: dict[str, Any]) -> list[str]:
    raw = item.get("quality_flags") or []
    if isinstance(raw, list):
        return [str(value or "").strip() for value in raw if str(value or "").strip()]
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(entry or "").strip() for entry in parsed if str(entry or "").strip()]
        return [part.strip() for part in re.split(r"[,，;；]\s*", value) if part.strip()]
    return []


def _has_blocking_quality_issue(item: dict[str, Any]) -> bool:
    stem = str(item.get("stem") or "").strip()
    if "[公式:" in stem:
        return True

    blocking_prefixes = (
        "formula_unconverted",
        "unknown_tokens",
        "choice_missing_options",
        "choice_options_incomplete",
        "stem_too_short",
    )
    return any(flag.startswith(blocking_prefixes) for flag in _quality_flags(item))


def _normalize_crawl_item(item: dict[str, Any], *, subject: str, domain: str) -> dict[str, Any] | None:
    question_id = str(item.get("question_id") or "").strip()
    stem = str(item.get("stem") or "").strip()
    if not question_id or len(stem) < 8:
        return None

    raw_knowledge = item.get("knowledge_points") or item.get("knowledge_point") or []
    if isinstance(raw_knowledge, list):
        knowledge_points = [str(value or "").strip() for value in raw_knowledge if str(value or "").strip()]
    elif isinstance(raw_knowledge, str):
        knowledge_points = [raw_knowledge.strip()] if raw_knowledge.strip() else []
    else:
        knowledge_points = []
    knowledge_points = list(dict.fromkeys([*knowledge_points, domain]))

    return {
        "question_id": question_id,
        "subject": subject,
        "question_type": str(item.get("question_type") or item.get("type") or "").strip(),
        "difficulty": str(item.get("difficulty") or "").strip(),
        "difficulty_value": item.get("difficulty_value"),
        "knowledge_point": "、".join(knowledge_points[:6]),
        "knowledge_points": knowledge_points,
        "source_url": str(item.get("source_url") or "").strip(),
        "stem": stem,
        "stem_fingerprint": str(item.get("stem_fingerprint") or item.get("stem_fp") or "").strip(),
        "answer": str(item.get("answer") or "").strip(),
        "analysis": str(item.get("analysis") or "").strip(),
        "quality_score": int(item.get("quality_score") or 0),
        "quality_flags": item.get("quality_flags") or "",
        "source": str(item.get("source") or "").strip(),
        "date": str(item.get("date") or "").strip(),
    }


def normalize_crawl_items(
    items: Sequence[dict[str, Any]],
    *,
    seen_ids: set[str],
    subject: str,
    domain: str,
    difficulty_value_max: float,
    require_difficulty_value: bool = True,
) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        if not question_id or question_id in seen_ids:
            continue
        if not _difficulty_value_ok(item, max_value=difficulty_value_max, require_value=require_difficulty_value):
            continue
        if _has_blocking_quality_issue(item):
            continue
        normalized = _normalize_crawl_item(item, subject=subject, domain=domain)
        if normalized is None:
            continue
        seen_ids.add(question_id)
        normalized_items.append(normalized)
    return normalized_items


async def load_existing_question_ids(*, user_id: str, subject: str) -> set[str]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(QuestionLibraryItem.question_id).where(
                QuestionLibraryItem.user_id == str(user_id or "").strip(),
                QuestionLibraryItem.subject == str(subject or "").strip(),
            )
        )
        return {str(value or "").strip() for value in result.scalars().all() if str(value or "").strip()}


async def delete_existing_crawled_library_items(*, user_id: str, subject: str) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            delete(QuestionLibraryItem).where(
                QuestionLibraryItem.user_id == str(user_id or "").strip(),
                QuestionLibraryItem.subject == str(subject or "").strip(),
                QuestionLibraryItem.origin == "crawled",
            )
        )
        await session.commit()
        try:
            return int(getattr(result, "rowcount", 0) or 0)
        except (TypeError, ValueError):
            return 0


def _log(config: CrawlImportConfig, message: str, **extra: Any) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "message": message, **extra}
    with config.log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


async def _crawl_query(
    crawler: ZujuanCrawler,
    config: CrawlImportConfig,
    *,
    plan_item: KeywordPlanItem,
    seen_ids: set[str],
) -> list[dict[str, Any]]:
    result = await crawler.search_by_keyword(
        keyword=plan_item.query,
        subject=config.subject,
        limit=config.limit_per_query,
        max_pages=config.max_pages,
        parse_content=config.parse_content,
        with_quality=True,
        min_quality_score=0,
        difficulty_value_max=config.difficulty_value_max,
        require_difficulty_value=config.require_difficulty_value,
        dedup_by_stem=True,
    )
    if not isinstance(result, dict) or not result.get("success"):
        _log(
            config,
            "query_failed",
            query=plan_item.query,
            domain=plan_item.domain,
            error=(result or {}).get("error") if isinstance(result, dict) else "invalid_result",
        )
        return []

    raw = result.get("questions")
    questions = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    normalized = normalize_crawl_items(
        questions,
        seen_ids=seen_ids,
        subject=config.subject,
        domain=plan_item.domain,
        difficulty_value_max=config.difficulty_value_max,
        require_difficulty_value=config.require_difficulty_value,
    )
    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    pages = trace.get("pages") if isinstance(trace, dict) else []
    _log(config, "query_done", query=plan_item.query, domain=plan_item.domain, fetched=len(normalized), pages=len(pages or []))
    return normalized


async def run_import(config: CrawlImportConfig) -> dict[str, Any]:
    os.environ.setdefault("ZUJUAN_USE_ENV_COOKIES_FOR_SEARCH", "0")
    os.environ.setdefault("ZUJUAN_USE_CACHED_ANTIBOT_COOKIES", "1")
    os.environ.setdefault("ZUJUAN_AUTO_BOOTSTRAP_COOKIES", "1")
    os.environ.setdefault("ZUJUAN_RATE_LIMIT_RPS", "1.2")
    os.environ.setdefault("ZUJUAN_RATE_LIMIT_BURST", "2")

    plan = build_keyword_plan(config)
    if not plan:
        raise SystemExit("empty_keyword_plan")

    config.log_path.unlink(missing_ok=True)
    config.summary_path.unlink(missing_ok=True)
    existing_ids = await load_existing_question_ids(user_id=config.user_id, subject=config.subject)
    replaced_existing = 0
    if config.replace_existing and not config.dry_run:
        replaced_existing = await delete_existing_crawled_library_items(user_id=config.user_id, subject=config.subject)
        existing_ids = set()
    seen_ids = set() if config.replace_existing else set(existing_ids)
    inserted = 0
    domain_counts: dict[str, int] = {}

    _log(
        config,
        "start",
        user_id=config.user_id,
        subject=config.subject,
        target=config.target,
        existing=len(existing_ids),
        dry_run=config.dry_run,
        replace_existing=config.replace_existing,
        replaced_existing=replaced_existing,
    )

    crawler = ZujuanCrawler(subject=config.subject)
    await crawler.initialize()
    try:
        # 同一轮内的关键词查询并发执行（信号量限并发，实际请求速率仍由
        # ZUJUAN_RATE_LIMIT_RPS 限流桶约束）；seen_ids 的 check+add 在
        # normalize_crawl_items 内同步完成，事件循环下无竞争。
        concurrency = max(1, min(int(config.concurrency or 1), 4))
        sem = asyncio.Semaphore(concurrency)

        async def _run_plan_item(item: KeywordPlanItem) -> list[dict[str, Any]]:
            async with sem:
                if inserted >= config.target:
                    return []
                return await _crawl_query(crawler, config, plan_item=item, seen_ids=seen_ids)

        for round_index in range(1, max(1, config.rounds) + 1):
            if inserted >= config.target:
                break
            # return_exceptions：单查询的网络/解析异常按 query_failed 记录并继续，
            # 否则 gather 立刻抛出会丢掉本轮其余查询已抓到的结果，且外层 finally
            # 关闭 crawler 时兄弟协程仍在飞行中。
            round_results = await asyncio.gather(
                *[_run_plan_item(item) for item in plan], return_exceptions=True
            )
            for plan_item, batch in zip(plan, round_results):
                if inserted >= config.target:
                    break
                if isinstance(batch, asyncio.CancelledError):
                    raise batch
                if isinstance(batch, BaseException):
                    _log(
                        config,
                        "query_failed",
                        query=plan_item.query,
                        domain=plan_item.domain,
                        error=f"{type(batch).__name__}: {batch}",
                    )
                    continue
                if not batch:
                    continue
                remaining = config.target - inserted
                batch = batch[:remaining]
                if not config.dry_run:
                    await upsert_question_cache(batch)
                    await upsert_question_library_items(
                        user_id=config.user_id,
                        items=[
                            {
                                "question_id": item["question_id"],
                                "subject": config.subject,
                                "origin": "crawled",
                                "hidden": False,
                            }
                            for item in batch
                        ],
                    )
                inserted += len(batch)
                domain_counts[plan_item.domain] = domain_counts.get(plan_item.domain, 0) + len(batch)
                summary = {
                    "success": inserted >= config.target,
                    "target": config.target,
                    "inserted": inserted,
                    "existing": len(existing_ids),
                    "replaced_existing": replaced_existing,
                    "unique_seen": len(seen_ids),
                    "domain_counts": domain_counts,
                    "last_query": plan_item.query,
                    "round": round_index,
                    "concurrency": concurrency,
                    "dry_run": config.dry_run,
                    "difficulty_value_max": config.difficulty_value_max,
                }
                config.summary_path.parent.mkdir(parents=True, exist_ok=True)
                config.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                _log(config, "batch_saved" if not config.dry_run else "batch_dry_run", **summary)
            if inserted >= config.target:
                break
        final = {
            "success": inserted >= config.target,
            "target": config.target,
            "inserted": inserted,
            "existing": len(existing_ids),
            "replaced_existing": replaced_existing,
            "unique_seen": len(seen_ids),
            "domain_counts": domain_counts,
            "dry_run": config.dry_run,
            "difficulty_value_max": config.difficulty_value_max,
        }
        config.summary_path.parent.mkdir(parents=True, exist_ok=True)
        config.summary_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(config, "done", **final)
        return final
    finally:
        await crawler.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.question_library_crawl",
        description="批量爬取题目并写入本地题库。",
    )
    parser.add_argument("--interactive", action="store_true", default=False, help="使用交互式 TUI 配置爬取任务。")
    parser.add_argument("--non-interactive", action="store_true", default=False, help="空参数时也直接使用默认值执行。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--subject", default="高中物理")
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument(
        "--domains",
        default="all",
        help="all | mechanics | electromagnetism，也可用中文：力学,电磁学",
    )
    parser.add_argument("--keywords", default="", help="逗号分隔的自定义关键词；提供后覆盖默认领域关键词。")
    parser.add_argument("--difficulty-value-max", type=float, default=0.65, help="组卷网难度系数上限；越小越难。")
    parser.add_argument("--allow-missing-difficulty-value", action="store_true", default=False)
    parser.add_argument("--limit-per-query", type=int, default=120)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="同一轮内并发的关键词查询数（1-4）；实际请求速率仍由 ZUJUAN_RATE_LIMIT_RPS 约束。",
    )
    parser.add_argument(
        "--parse-content",
        dest="parse_content",
        action="store_true",
        default=None,
        help="完整解析题干并转换公式；批量入库默认开启。",
    )
    parser.add_argument(
        "--no-parse-content",
        "--fast-preview",
        dest="parse_content",
        action="store_false",
        help="只取列表页快速预览，不建议用于入库。",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        default=False,
        help="先移除当前用户/学科下旧的爬取题，再重新爬取入库。",
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--log-path", default=".local/imports/question_library_crawl.jsonl")
    parser.add_argument("--summary-path", default=".local/imports/question_library_crawl_summary.json")
    return parser


def config_from_args(args: argparse.Namespace) -> CrawlImportConfig:
    return CrawlImportConfig(
        user_id=str(args.user_id or "1").strip() or "1",
        subject=str(args.subject or "高中物理").strip() or "高中物理",
        target=max(1, min(int(args.target or 1000), 10000)),
        domains=_normalize_domains(_split_csv(str(args.domains or "all"))),
        difficulty_value_max=max(0.0, min(float(args.difficulty_value_max), 1.0)),
        require_difficulty_value=not bool(args.allow_missing_difficulty_value),
        limit_per_query=max(1, min(int(args.limit_per_query or 120), 200)),
        max_pages=max(1, min(int(args.max_pages or 12), 50)),
        rounds=max(1, min(int(args.rounds or 3), 10)),
        concurrency=max(1, min(int(args.concurrency or 2), 4)),
        parse_content=True if args.parse_content is None else bool(args.parse_content),
        replace_existing=bool(args.replace_existing),
        dry_run=bool(args.dry_run),
        log_path=Path(str(args.log_path or ".local/imports/question_library_crawl.jsonl")),
        summary_path=Path(str(args.summary_path or ".local/imports/question_library_crawl_summary.json")),
        custom_keywords=_split_csv(str(args.keywords or "")),
    )


def _prompt_text(label: str, default: str, *, input_fn: InputFn, output_fn: OutputFn) -> str:
    prompt = f"{label} [{default}]: " if default else f"{label}: "
    try:
        value = input_fn(prompt)
    except EOFError:
        value = ""
    value = str(value or "").strip()
    return value or default


def _prompt_int(
    label: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    input_fn: InputFn,
    output_fn: OutputFn,
) -> int:
    while True:
        value = _prompt_text(label, str(default), input_fn=input_fn, output_fn=output_fn)
        try:
            parsed = int(value)
        except ValueError:
            output_fn(f"请输入 {minimum}-{maximum} 的整数。")
            continue
        if minimum <= parsed <= maximum:
            return parsed
        output_fn(f"请输入 {minimum}-{maximum} 的整数。")


def _prompt_float(
    label: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    input_fn: InputFn,
    output_fn: OutputFn,
) -> float:
    while True:
        value = _prompt_text(label, str(default), input_fn=input_fn, output_fn=output_fn)
        try:
            parsed = float(value)
        except ValueError:
            output_fn(f"请输入 {minimum:g}-{maximum:g} 之间的小数。")
            continue
        if minimum <= parsed <= maximum:
            return parsed
        output_fn(f"请输入 {minimum:g}-{maximum:g} 之间的小数。")


def _prompt_bool(label: str, default: bool, *, input_fn: InputFn, output_fn: OutputFn) -> bool:
    default_label = "Y/n" if default else "y/N"
    yes_values = {"y", "yes", "1", "true", "是", "确认", "执行"}
    no_values = {"n", "no", "0", "false", "否", "不", "取消"}
    while True:
        try:
            value = input_fn(f"{label} [{default_label}]: ")
        except EOFError:
            value = ""
        value = str(value or "").strip().lower()
        if not value:
            return default
        if value in yes_values:
            return True
        if value in no_values:
            return False
        output_fn("请输入 y 或 n。")


def _domain_choice_from_defaults(defaults: CrawlImportConfig) -> str:
    if defaults.custom_keywords:
        return "4"
    try:
        domains = _normalize_domains(defaults.domains)
    except SystemExit:
        return "1"
    if domains == ("力学",):
        return "2"
    if domains == ("电磁学",):
        return "3"
    return "1"


def _prompt_domains(
    defaults: CrawlImportConfig,
    *,
    input_fn: InputFn,
    output_fn: OutputFn,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    options = {
        "1": ("全部默认关键词", ("all",)),
        "2": ("力学", ("力学",)),
        "3": ("电磁学", ("电磁学",)),
        "4": ("自定义关键词", ("all",)),
    }
    output_fn("")
    output_fn("题目范围")
    output_fn("  1. 全部默认关键词")
    output_fn("  2. 力学")
    output_fn("  3. 电磁学")
    output_fn("  4. 自定义关键词")
    default_choice = _domain_choice_from_defaults(defaults)
    while True:
        try:
            choice = input_fn(f"选择范围 [默认 {default_choice}]: ")
        except EOFError:
            choice = ""
        choice = str(choice or default_choice).strip()
        if choice in options:
            break
        output_fn("请输入 1-4。")

    domains = options[choice][1]
    if choice != "4":
        return domains, ()

    default_keywords = "，".join(defaults.custom_keywords)
    keywords = _split_csv(
        _prompt_text("自定义关键词，逗号分隔", default_keywords, input_fn=input_fn, output_fn=output_fn)
    )
    if keywords:
        return domains, keywords
    output_fn("未输入自定义关键词，改用全部默认关键词。")
    return ("all",), ()


def _format_domains(domains: Sequence[str]) -> str:
    normalized = _normalize_domains(domains)
    return "力学+电磁学" if normalized == ("all",) else "、".join(normalized)


def _format_config_summary(config: CrawlImportConfig) -> list[str]:
    keywords = "默认关键词" if not config.custom_keywords else "、".join(config.custom_keywords)
    return [
        f"用户: {config.user_id}",
        f"学科: {config.subject}",
        f"目标数量: {config.target}",
        f"范围: {_format_domains(config.domains)}",
        f"关键词: {keywords}",
        f"难度系数上限: {config.difficulty_value_max}",
        f"每个关键词最多抓取: {config.limit_per_query}",
        f"每个关键词最多翻页: {config.max_pages}",
        f"轮次: {config.rounds}",
        f"解析公式内容: {'是' if config.parse_content else '否'}",
        f"覆盖旧爬取题: {'是' if config.replace_existing else '否'}",
        f"只试跑不入库: {'是' if config.dry_run else '否'}",
        f"日志: {config.log_path}",
        f"摘要: {config.summary_path}",
    ]


def prompt_interactive_config(
    defaults: CrawlImportConfig | None = None,
    *,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
) -> CrawlImportConfig:
    defaults = defaults or CrawlImportConfig()
    output_fn("交互式批量爬取 - 本地题库")
    output_fn("按 Enter 使用默认值；最后确认后才会开始爬取。")
    output_fn("")

    user_id = _prompt_text("用户 ID", defaults.user_id, input_fn=input_fn, output_fn=output_fn)
    subject = _prompt_text("学科", defaults.subject, input_fn=input_fn, output_fn=output_fn)
    target = _prompt_int(
        "目标入库数量",
        defaults.target,
        minimum=1,
        maximum=10000,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    domains, custom_keywords = _prompt_domains(defaults, input_fn=input_fn, output_fn=output_fn)
    difficulty_value_max = _prompt_float(
        "难度系数上限，越小越难",
        defaults.difficulty_value_max,
        minimum=0.0,
        maximum=1.0,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    limit_per_query = _prompt_int(
        "每个关键词最多抓取",
        defaults.limit_per_query,
        minimum=1,
        maximum=200,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    max_pages = _prompt_int(
        "每个关键词最多翻页",
        defaults.max_pages,
        minimum=1,
        maximum=50,
        input_fn=input_fn,
        output_fn=output_fn,
    )
    rounds = _prompt_int("轮次", defaults.rounds, minimum=1, maximum=10, input_fn=input_fn, output_fn=output_fn)
    parse_content = _prompt_bool("解析公式内容，速度较慢", defaults.parse_content, input_fn=input_fn, output_fn=output_fn)
    replace_existing = _prompt_bool("覆盖当前学科已有爬取题", defaults.replace_existing, input_fn=input_fn, output_fn=output_fn)
    dry_run = _prompt_bool("只试跑不入库", defaults.dry_run, input_fn=input_fn, output_fn=output_fn)

    config = CrawlImportConfig(
        user_id=user_id,
        subject=subject,
        target=target,
        domains=domains,
        difficulty_value_max=difficulty_value_max,
        require_difficulty_value=defaults.require_difficulty_value,
        limit_per_query=limit_per_query,
        max_pages=max_pages,
        rounds=rounds,
        concurrency=defaults.concurrency,
        parse_content=parse_content,
        replace_existing=replace_existing,
        dry_run=dry_run,
        log_path=defaults.log_path,
        summary_path=defaults.summary_path,
        custom_keywords=custom_keywords,
    )

    output_fn("")
    output_fn("配置预览")
    for line in _format_config_summary(config):
        output_fn(f"  {line}")
    if not _prompt_bool("开始执行", True, input_fn=input_fn, output_fn=output_fn):
        raise SystemExit("cancelled")
    return config


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    if args.interactive and args.non_interactive:
        parser.error("--interactive and --non-interactive cannot be used together")
    if args.interactive or (not argv and not args.non_interactive):
        config = prompt_interactive_config(config)
    result = asyncio.run(run_import(config))
    if not result.get("success"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
