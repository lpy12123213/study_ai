import asyncio
import hashlib
import os
import time
from collections import OrderedDict, deque
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from backend.api.middleware.request_id import ensure_request_id

CallNext = Callable[[Request], Awaitable[Response]]
ClientIpGetter = Callable[[Request], str]


class SlidingWindowRateLimiter:
    """Bounded sliding-window rate limiter with LRU key eviction."""

    def __init__(self, *, max_requests: int, window_s: float, max_keys: int) -> None:
        self.max_requests = max(0, int(max_requests or 0))
        self.window_s = max(0.001, float(window_s or 0.0))
        self.max_keys = max(1, int(max_keys or 1))
        self._lock = asyncio.Lock()
        self._hits: "OrderedDict[str, deque[float]]" = OrderedDict()

    def _prune_bucket(self, bucket: deque[float], *, now: float) -> None:
        while bucket and (now - bucket[0]) > self.window_s:
            bucket.popleft()

    def _evict_if_needed(self) -> None:
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)

    async def is_limited(self, key: str) -> bool:
        if self.max_requests <= 0:
            return False

        k = str(key or "").strip()
        if not k:
            return False

        now = time.monotonic()
        async with self._lock:
            bucket = self._hits.get(k)
            if not bucket:
                self._hits.pop(k, None)
                return False

            self._prune_bucket(bucket, now=now)
            if not bucket:
                self._hits.pop(k, None)
                return False

            self._hits.move_to_end(k)
            return len(bucket) >= self.max_requests

    async def allow(self, key: str) -> bool:
        if self.max_requests <= 0:
            return True

        k = str(key or "").strip()
        if not k:
            return True

        now = time.monotonic()
        async with self._lock:
            bucket = self._hits.get(k)
            if bucket is None:
                bucket = deque()
                self._hits[k] = bucket

            self._prune_bucket(bucket, now=now)
            if len(bucket) >= self.max_requests:
                self._hits.move_to_end(k)
                return False

            bucket.append(now)
            self._hits.move_to_end(k)
            self._evict_if_needed()
            return True

    async def record(self, key: str) -> None:
        if self.max_requests <= 0:
            return

        k = str(key or "").strip()
        if not k:
            return

        now = time.monotonic()
        async with self._lock:
            bucket = self._hits.get(k)
            if bucket is None:
                bucket = deque()
                self._hits[k] = bucket

            self._prune_bucket(bucket, now=now)
            bucket.append(now)
            self._hits.move_to_end(k)
            self._evict_if_needed()


def _rate_limited_response(request: Request) -> JSONResponse:
    rid = ensure_request_id(request)
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "rate_limited",
            "error": {"code": "rate_limited", "message": "rate_limited", "request_id": rid},
        },
    )
    response.headers.setdefault("X-Request-ID", rid)
    return response


def register_rate_limit_middleware(app: FastAPI, *, client_ip: ClientIpGetter) -> None:
    rate_limit_max = int(os.getenv("API_RATE_LIMIT_MAX_REQUESTS") or "300")
    rate_limit_window_s = float(os.getenv("API_RATE_LIMIT_WINDOW_S") or "60")
    rate_limit_keys_max = int(os.getenv("API_RATE_LIMIT_MAX_KEYS") or "20000")
    rate_limit_max = max(0, min(rate_limit_max, 50_000))
    rate_limit_window_s = max(1.0, min(rate_limit_window_s, 3600.0))
    rate_limit_keys_max = max(100, min(rate_limit_keys_max, 200_000))

    api_rate_limiter = SlidingWindowRateLimiter(
        max_requests=rate_limit_max,
        window_s=rate_limit_window_s,
        max_keys=rate_limit_keys_max,
    )

    auth_fail_limit_max = int(os.getenv("AUTH_RATE_LIMIT_MAX_FAILS") or "5")
    auth_fail_limit_window_s = float(os.getenv("AUTH_RATE_LIMIT_WINDOW_S") or "900")
    auth_fail_limit_max = max(0, min(auth_fail_limit_max, 10_000))
    auth_fail_limit_window_s = max(1.0, min(auth_fail_limit_window_s, 24 * 3600.0))

    auth_fail_limiter = SlidingWindowRateLimiter(
        max_requests=auth_fail_limit_max,
        window_s=auth_fail_limit_window_s,
        max_keys=min(rate_limit_keys_max, 50_000),
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: CallNext) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)

        auth_path = path in {"/api/auth/register"}
        host = client_ip(request)
        auth_key = f"auth_fail:ip:{host}"
        if auth_path and await auth_fail_limiter.is_limited(auth_key):
            return _rate_limited_response(request)

        key = ""
        auth = str(request.headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                key = f"token:{digest}"

        if not key:
            key = f"ip:{host}"

        if not await api_rate_limiter.allow(key):
            return _rate_limited_response(request)

        response = await call_next(request)
        if auth_path and response.status_code in {400, 401, 403}:
            await auth_fail_limiter.record(auth_key)
        return response
