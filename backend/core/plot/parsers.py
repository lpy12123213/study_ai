from __future__ import annotations

from typing import Any, List, Tuple

from backend.shared.numparse import clamp_float as _clamp_float
from backend.shared.numparse import clamp_int as _clamp_int  # noqa: F401  # re-export for charts/geometry/schematic


def _as_str(value: Any) -> str:
    return str(value or "").strip()





def _parse_range(value: Any, *, default: Tuple[float, float], min_span: float = 1e-6) -> Tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        a = _clamp_float(value[0], default=default[0], min_value=-1e9, max_value=1e9)
        b = _clamp_float(value[1], default=default[1], min_value=-1e9, max_value=1e9)
        if a == b:
            b = a + (1.0 if abs(a) < 1e-3 else abs(a) * 0.1 + 1.0)
        if abs(b - a) < min_span:
            b = a + min_span
        return (min(a, b), max(a, b))
    if isinstance(value, dict):
        a = _clamp_float(value.get("min"), default=default[0], min_value=-1e9, max_value=1e9)
        b = _clamp_float(value.get("max"), default=default[1], min_value=-1e9, max_value=1e9)
        if a == b:
            b = a + (1.0 if abs(a) < 1e-3 else abs(a) * 0.1 + 1.0)
        if abs(b - a) < min_span:
            b = a + min_span
        return (min(a, b), max(a, b))
    return default


def _iter_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []
