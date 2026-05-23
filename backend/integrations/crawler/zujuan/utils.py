from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

PROVINCE_UNLIMITED_ALIASES = {
    "不限",
    "不限地区",
    "不限省份",
    "全国",
    "全國",
    "全部",
    "all",
    "ALL",
}


def _extract_js_var_json(text: str, var_name: str) -> Optional[str]:
    """
    从类似 `var xxx=[...]` / `var xxx={...}` 的 JS 文本中提取出 `xxx` 的 JSON 值。

    说明：/zujuan-api/base 不是纯 JSON，通常会包含 `var edu=[...]` 及其他内容，
    直接用正则截到末尾会导致 json.loads 失败。这里用简单的括号匹配截取完整值。
    """
    marker = f"var {var_name}="
    idx = (text or "").find(marker)
    if idx < 0:
        return None

    start = None
    open_ch = None
    for ch in ("[", "{"):
        pos = (text or "").find(ch, idx + len(marker))
        if pos >= 0 and (start is None or pos < start):
            start = pos
            open_ch = ch

    if start is None or open_ch is None:
        return None

    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text or "")):
        ch = (text or "")[i]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
                continue
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == open_ch:
            depth += 1
            continue
        if ch == close_ch:
            depth -= 1
            if depth == 0:
                return (text or "")[start : i + 1]

    return None


def _parse_base_json(text: str) -> Optional[List[Dict[str, Any]]]:
    """解析 /zujuan-api/base 中的 `var edu=[...]`。"""
    raw = _extract_js_var_json(text or "", "edu")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return None
    except json.JSONDecodeError:
        return None


def _parse_province_list_json(text: str) -> Optional[List[Dict[str, Any]]]:
    """解析 /zujuan-api/base-province 中的 `var province_list=[...]`。"""
    raw = _extract_js_var_json(text or "", "province_list")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return None
    except json.JSONDecodeError:
        return None


def _normalize_province_name(name: str) -> str:
    """Normalize province names for matching (e.g. 北京市 -> 北京)."""
    s = re.sub(r"\\s+", "", (name or "").strip())
    if not s:
        return ""
    if s in PROVINCE_UNLIMITED_ALIASES:
        return "不限"
    suffixes = [
        "特别行政区",
        "特别行政區",
        "维吾尔自治区",
        "維吾爾自治區",
        "壮族自治区",
        "壯族自治區",
        "回族自治区",
        "回族自治區",
        "自治区",
        "自治區",
        "省",
        "市",
    ]
    for suffix in suffixes:
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    return s


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if not s:
            return default
        return int(s)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return None
        return float(s)
    except (TypeError, ValueError):
        return None
