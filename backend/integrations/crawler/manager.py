from __future__ import annotations

import asyncio
from typing import Dict, Tuple

from backend.core.logging_utils import get_logger
from backend.core.settings import DEFAULT_SUBJECT
from backend.core.subjects import resolve_subject
from backend.integrations.crawler.interface import CrawlerInterface
from backend.integrations.crawler.zujuan_crawler import ZujuanCrawler

# Keep per-subject crawler instances to avoid cross-request races when switching subjects.
_crawlers: Dict[Tuple[str, str], CrawlerInterface] = {}
_inflight: Dict[Tuple[str, str], asyncio.Future] = {}
_lock = asyncio.Lock()
logger = get_logger(__name__)


async def get_crawler(*, subject: str = "", edu_level: str = "", strict: bool = True) -> CrawlerInterface:
    """
    Get (or create) a crawler instance for the backend app.

    Notes:
    - The crawler is expensive to initialize (Playwright); cache instances per subject.
    - Subject resolution is strict by default to avoid cross-subject leakage.
    - Uses asyncio.Lock + in-flight futures to prevent duplicate initialization.
    """
    subject_input = (subject or DEFAULT_SUBJECT).strip()
    edu_level_clean = (edu_level or "").strip()
    resolved_subject = resolve_subject(subject_input, edu_level=edu_level_clean, strict=strict)
    key = (resolved_subject, edu_level_clean)

    async with _lock:
        existing = _crawlers.get(key)
        if existing is not None:
            return existing

        fut = _inflight.get(key)
        if fut is None:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            _inflight[key] = fut
            creator = True
        else:
            creator = False

    if not creator:
        return await fut

    crawler: CrawlerInterface = ZujuanCrawler(subject=resolved_subject)
    try:
        await crawler.initialize()
    except BaseException as exc:
        async with _lock:
            inflight = _inflight.pop(key, None)
            if inflight is not None and not inflight.done():
                inflight.set_exception(exc)
        raise

    async with _lock:
        _crawlers[key] = crawler
        inflight = _inflight.pop(key, None)
        if inflight is not None and not inflight.done():
            inflight.set_result(crawler)

    return crawler


async def close_crawler() -> None:
    """Close cached crawler instances (best-effort)."""
    global _crawlers
    global _inflight

    async with _lock:
        crawlers = list(_crawlers.values())
        _crawlers = {}

        inflight = list(_inflight.values())
        _inflight = {}

    for fut in inflight:
        try:
            if not fut.done():
                fut.set_exception(RuntimeError("crawler_closed"))
        except Exception:
            logger.exception("failed to cancel inflight crawler future")

    for crawler in crawlers:
        try:
            await crawler.close()
        except Exception:
            logger.exception("crawler_close_failed")
