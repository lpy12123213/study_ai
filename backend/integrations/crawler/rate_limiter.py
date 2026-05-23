from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def _now_s() -> float:
    return time.monotonic()


@dataclass
class _LimiterState:
    tokens: float
    updated_at_s: float


class AsyncTokenBucket:
    """A tiny async token-bucket limiter (process-local).

    This is intentionally simple:
    - Limits average rate to `rate_per_s` with short bursts up to `burst`.
    - Uses a single asyncio.Lock so concurrent callers share state.
    """

    def __init__(self, *, rate_per_s: float, burst: int) -> None:
        self.rate_per_s = max(0.0, float(rate_per_s or 0.0))
        self.burst = max(1, int(burst or 1))
        self._lock = asyncio.Lock()
        self._st = _LimiterState(tokens=float(self.burst), updated_at_s=_now_s())

    async def acquire(self, tokens: float = 1.0) -> None:
        need = max(0.0001, float(tokens or 1.0))
        if self.rate_per_s <= 0.0:
            # Disabled.
            return

        while True:
            async with self._lock:
                now = _now_s()
                elapsed = max(0.0, float(now - self._st.updated_at_s))
                self._st.updated_at_s = now

                # Refill tokens.
                self._st.tokens = min(float(self.burst), float(self._st.tokens + elapsed * self.rate_per_s))

                if self._st.tokens >= need:
                    self._st.tokens -= need
                    return

                missing = need - self._st.tokens
                wait_s = missing / self.rate_per_s if self.rate_per_s > 0 else 0.05

            # Sleep outside lock to avoid blocking other coroutines.
            await asyncio.sleep(min(5.0, max(0.0, wait_s)))

    async def __aenter__(self) -> "AsyncTokenBucket":
        await self.acquire(1.0)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class SQLiteTokenBucket:
    """A SQLite-backed token bucket shared across processes."""

    def __init__(self, *, key: str, rate_per_s: float, burst: int, path: str | Path) -> None:
        self.key = str(key or "").strip() or "default"
        self.rate_per_s = max(0.0, float(rate_per_s or 0.0))
        self.burst = max(1, int(burst or 1))
        self.path = Path(path)
        self._lock = asyncio.Lock()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawler_rate_limiter (
              key TEXT PRIMARY KEY,
              tokens REAL NOT NULL,
              updated_at_s REAL NOT NULL
            )
            """
        )

    def _load_state(self, conn: sqlite3.Connection, *, now: float) -> _LimiterState:
        row = conn.execute(
            "SELECT tokens, updated_at_s FROM crawler_rate_limiter WHERE key = ?",
            (self.key,),
        ).fetchone()
        if row is None:
            return _LimiterState(tokens=float(self.burst), updated_at_s=now)
        try:
            tokens = float(row[0])
            updated_at_s = float(row[1])
        except (TypeError, ValueError):
            tokens = float(self.burst)
            updated_at_s = now
        return _LimiterState(tokens=tokens, updated_at_s=updated_at_s)

    def _save_state(self, conn: sqlite3.Connection, state: _LimiterState) -> None:
        conn.execute(
            """
            INSERT INTO crawler_rate_limiter(key, tokens, updated_at_s)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET tokens = excluded.tokens, updated_at_s = excluded.updated_at_s
            """,
            (self.key, float(state.tokens), float(state.updated_at_s)),
        )

    async def acquire(self, tokens: float = 1.0) -> None:
        need = max(0.0001, float(tokens or 1.0))
        if self.rate_per_s <= 0.0:
            return

        while True:
            wait_s = 0.0
            async with self._lock:
                now = time.time()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.path))
                try:
                    self._ensure_schema(conn)
                    state = self._load_state(conn, now=now)
                    elapsed = max(0.0, now - float(state.updated_at_s))
                    state.tokens = min(float(self.burst), float(state.tokens) + elapsed * self.rate_per_s)
                    state.updated_at_s = now
                    if state.tokens >= need:
                        state.tokens -= need
                        self._save_state(conn, state)
                        conn.commit()
                        return
                    missing = need - state.tokens
                    wait_s = missing / self.rate_per_s if self.rate_per_s > 0.0 else 0.05
                    self._save_state(conn, state)
                    conn.commit()
                finally:
                    conn.close()

            await asyncio.sleep(min(5.0, max(0.0, wait_s)))

    async def __aenter__(self) -> "SQLiteTokenBucket":
        await self.acquire(1.0)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


_registry: Dict[str, AsyncTokenBucket] = {}


def get_rate_limiter(*, key: str, rate_per_s: float, burst: int) -> AsyncTokenBucket:
    """Get or create a shared limiter instance by key."""

    k = str(key or "").strip() or "default"
    existing = _registry.get(k)
    if existing is not None:
        return existing
    limiter = AsyncTokenBucket(rate_per_s=rate_per_s, burst=burst)
    _registry[k] = limiter
    return limiter
