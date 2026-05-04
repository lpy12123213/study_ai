from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from backend.core.logging_utils import get_logger

__all__ = [
    "TTLCache",
    "cache_registry_stats",
]

logger = get_logger(__name__)


_registry_lock = threading.Lock()
_cache_registry: Dict[str, "TTLCache"] = {}


def _now_s() -> float:
    return time.time()


def cache_registry_stats() -> Dict[str, Any]:
    """Return a JSON-serializable snapshot of registered caches."""

    with _registry_lock:
        items = list(_cache_registry.items())

    out: Dict[str, Any] = {}
    for name, cache in items:
        try:
            out[name] = cache.stats()
        except Exception:
            logger.exception("ttl_cache_stats_failed", extra={"cache": name})
            out[name] = {"name": name, "error": "stats_failed"}
    return out


class TTLCache:
    """A tiny in-process LRU + TTL cache with basic hit-rate stats."""

    def __init__(
        self,
        *,
        name: str,
        max_entries: int = 1024,
        default_ttl_s: float = 0.0,
        register: bool = True,
    ) -> None:
        self.name = str(name or "").strip() or "cache"
        self.max_entries = max(1, int(max_entries or 1))
        self.default_ttl_s = float(default_ttl_s or 0.0)

        # key -> (expires_at_s, value)
        self._data: "OrderedDict[Any, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()

        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0
        self._expires = 0

        if register:
            with _registry_lock:
                _cache_registry[self.name] = self

    def __len__(self) -> int:  # pragma: no cover
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def get(self, key: Any) -> Optional[Any]:  # noqa: ANN401
        now = _now_s()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None

            expires_at, value = item
            if expires_at > 0.0 and now >= expires_at:
                self._expires += 1
                self._misses += 1
                try:
                    del self._data[key]
                except Exception:
                    logger.warning("ttl_cache_expired_delete_failed", extra={"cache": self.name}, exc_info=True)
                return None

            self._hits += 1
            try:
                self._data.move_to_end(key)
            except Exception:
                logger.warning("ttl_cache_lru_touch_failed", extra={"cache": self.name}, exc_info=True)
            return value

    def set(self, key: Any, value: Any, *, ttl_s: Optional[float] = None) -> None:  # noqa: ANN401
        now = _now_s()
        ttl = self.default_ttl_s if ttl_s is None else float(ttl_s or 0.0)
        expires_at = (now + ttl) if ttl and ttl > 0 else 0.0

        with self._lock:
            self._sets += 1
            self._data[key] = (expires_at, value)
            try:
                self._data.move_to_end(key)
            except Exception:
                logger.warning("ttl_cache_lru_touch_failed", extra={"cache": self.name}, exc_info=True)

            while len(self._data) > self.max_entries:
                try:
                    self._data.popitem(last=False)
                    self._evictions += 1
                except Exception:
                    logger.exception("ttl_cache_evict_failed", extra={"cache": self.name})
                    break

    def delete(self, key: Any) -> None:  # noqa: ANN401
        with self._lock:
            try:
                self._data.pop(key, None)
            except Exception:
                logger.exception("ttl_cache_delete_failed", extra={"cache": self.name})
                return

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            size = len(self._data)
            hits = int(self._hits)
            misses = int(self._misses)
            sets = int(self._sets)
            evictions = int(self._evictions)
            expires = int(self._expires)

        total = hits + misses
        hit_rate = float(hits) / float(total) if total > 0 else None
        return {
            "name": self.name,
            "size": size,
            "max_entries": int(self.max_entries),
            "default_ttl_s": float(self.default_ttl_s),
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
            "sets": sets,
            "evictions": evictions,
            "expires": expires,
        }
