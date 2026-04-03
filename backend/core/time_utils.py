from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "utcnow",
    "utcnow_naive",
    "utcnow_iso_z",
]


def utcnow() -> datetime:
    """Timezone-aware UTC now."""

    return datetime.now(UTC)


def utcnow_naive() -> datetime:
    """Naive UTC now (for legacy SQLite schemas that store naive timestamps)."""

    return datetime.now(UTC).replace(tzinfo=None)


def utcnow_iso_z() -> str:
    """UTC now as an ISO-like string ending in `Z` (compatible with most frontends)."""

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

