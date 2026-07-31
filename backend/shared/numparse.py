"""Shared numeric parsing/clamping helpers.

These replace the per-module ``_clamp_int`` / ``_clamp_float`` copies that had
drifted in signature (``min_v`` vs ``min_value``) and edge-case behavior (NaN
handling, whether the fallback default itself is clamped).
"""

from __future__ import annotations

import math
from typing import Any, Optional


def clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    """Parse ``value`` as int and clamp into ``[min_value, max_value]``.

    Unparseable values fall back to ``default`` (which is clamped as well).
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def clamp_float(value: Any, *, default: float, min_value: float, max_value: float) -> float:
    """Parse ``value`` as float and clamp into ``[min_value, max_value]``.

    Unparseable, NaN and Inf values fall back to ``default``.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = default
    if math.isnan(n) or math.isinf(n):
        n = default
    return max(min_value, min(max_value, n))


def clamp_int_optional(value: Any, *, default: Optional[int], min_value: int, max_value: int) -> Optional[int]:
    """Optional-returning variant of :func:`clamp_int`; ``default`` may be ``None``."""
    n: Optional[int]
    if value is None:
        n = default
    else:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = default
    if n is None:
        return None
    return max(min_value, min(max_value, n))


def clamp_float_optional(
    value: Any, *, default: Optional[float], min_value: float, max_value: float
) -> Optional[float]:
    """Optional-returning variant of :func:`clamp_float`; ``default`` may be ``None``."""
    n: Optional[float]
    if value is None:
        n = default
    else:
        try:
            n = float(value)
        except (TypeError, ValueError):
            n = default
    if n is None:
        return None
    if math.isnan(n) or math.isinf(n):
        n = default
        if n is None:
            return None
    return max(min_value, min(max_value, n))
