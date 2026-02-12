from __future__ import annotations

import asyncio
from typing import Optional

from backend.config import DEFAULT_SUBJECT
from backend.subjects import resolve_subject
from backend.crawler.zujuan_crawler import ZujuanCrawler

_crawler: Optional[ZujuanCrawler] = None
_lock = asyncio.Lock()


async def get_crawler(*, subject: str = "", edu_level: str = "", strict: bool = True) -> ZujuanCrawler:
    """
    Get (or create) a shared crawler instance for the backend app.

    Notes:
    - The crawler is expensive to initialize (Playwright); keep one instance and switch subject when needed.
    - Subject resolution is strict by default to avoid cross-subject leakage.
    - Uses asyncio.Lock to prevent concurrent subject-switching race conditions.
    """
    global _crawler

    subject_input = (subject or DEFAULT_SUBJECT).strip()
    resolved_subject = resolve_subject(subject_input, edu_level=(edu_level or "").strip(), strict=strict)

    async with _lock:
        if _crawler is None:
            _crawler = ZujuanCrawler(subject=resolved_subject)
            await _crawler.initialize()
        elif _crawler.subject != resolved_subject:
            _crawler.set_subject(resolved_subject)

    return _crawler


async def close_crawler() -> None:
    """Close the shared crawler instance (best-effort)."""
    global _crawler
    async with _lock:
        if _crawler is None:
            return
        await _crawler.close()
        _crawler = None
