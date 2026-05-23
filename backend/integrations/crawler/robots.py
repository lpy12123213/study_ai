from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

DEFAULT_CRAWLER_USER_AGENT = "StudyAI/1.0 (+https://github.com/local/study_ai; contact=local-admin)"


class RobotsDisallowedError(PermissionError):
    """Raised when robots.txt disallows the requested URL."""


@dataclass
class RobotsPolicy:
    parser: RobotFileParser
    fetched_at_s: float
    error: str = ""


@dataclass
class RobotsTxtCache:
    ttl_s: float = 3600.0
    fetch_timeout_s: float = 8.0
    policies: dict[str, RobotsPolicy] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _origin(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("robots requires an absolute http(s) URL")
        return f"{parsed.scheme}://{parsed.netloc}"

    def _lock_for(self, origin: str) -> asyncio.Lock:
        lock = self._locks.get(origin)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[origin] = lock
        return lock

    async def prepare_origin(self, url: str, *, user_agent: str = DEFAULT_CRAWLER_USER_AGENT) -> RobotsPolicy:
        origin = self._origin(url)
        current = self.policies.get(origin)
        now = time.time()
        if current is not None and now - current.fetched_at_s < self.ttl_s:
            return current

        async with self._lock_for(origin):
            current = self.policies.get(origin)
            now = time.time()
            if current is not None and now - current.fetched_at_s < self.ttl_s:
                return current
            policy = await self._fetch_policy(origin=origin, user_agent=user_agent)
            self.policies[origin] = policy
            return policy

    async def _fetch_policy(self, *, origin: str, user_agent: str) -> RobotsPolicy:
        parser = RobotFileParser()
        robots_url = f"{origin.rstrip('/')}/robots.txt"
        parser.set_url(robots_url)
        headers = {"User-Agent": user_agent or DEFAULT_CRAWLER_USER_AGENT, "Accept": "text/plain,*/*;q=0.8"}
        try:
            async with httpx.AsyncClient(timeout=self.fetch_timeout_s, headers=headers, follow_redirects=True) as client:
                resp = await client.get(robots_url)
            if resp.status_code >= 400:
                parser.parse([])
                return RobotsPolicy(parser=parser, fetched_at_s=time.time(), error=f"http_{resp.status_code}")
            parser.parse((resp.text or "").splitlines())
            return RobotsPolicy(parser=parser, fetched_at_s=time.time())
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            parser.parse([])
            return RobotsPolicy(parser=parser, fetched_at_s=time.time(), error=str(exc))

    async def allowed(self, url: str, *, user_agent: str = DEFAULT_CRAWLER_USER_AGENT) -> bool:
        policy = await self.prepare_origin(url, user_agent=user_agent)
        ua = user_agent or DEFAULT_CRAWLER_USER_AGENT
        try:
            return bool(policy.parser.can_fetch(ua, url))
        except (TypeError, ValueError):
            return False

    async def assert_allowed(self, url: str, *, user_agent: str = DEFAULT_CRAWLER_USER_AGENT) -> None:
        if not await self.allowed(url, user_agent=user_agent):
            raise RobotsDisallowedError(f"robots.txt disallows fetch: {url}")

    async def crawl_delay(self, url: str, *, user_agent: str = DEFAULT_CRAWLER_USER_AGENT) -> float | None:
        policy = await self.prepare_origin(url, user_agent=user_agent)
        try:
            delay = policy.parser.crawl_delay(user_agent or DEFAULT_CRAWLER_USER_AGENT)
        except (AttributeError, TypeError, ValueError):
            delay = None
        try:
            return float(delay) if delay is not None else None
        except (TypeError, ValueError):
            return None


_CACHE = RobotsTxtCache()


def get_robots_cache() -> RobotsTxtCache:
    return _CACHE


def crawler_user_agent(*, browser_ua: str = "", contact: str = "") -> str:
    contact_value = str(contact or "local-admin").strip()
    product = f"StudyAI/1.0 (+https://github.com/local/study_ai; contact={contact_value})"
    base = str(browser_ua or "").strip()
    return f"{base} {product}".strip() if base else product
