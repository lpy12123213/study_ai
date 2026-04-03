"""Metaso AI Search (direct API).

This module integrates with Metaso's official HTTP API so the backend can use
Metaso results without requiring a separate MCP process.

API base URL default: https://metaso.cn/api/v1
Endpoints used:
- POST /search
- POST /ask (Q&A; returns synthesized answer + sources)
- POST /reader (optional)
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import METASO_API_KEY, METASO_BASE_URL, METASO_TIMEOUT

logger = get_logger(__name__)

_SCOPE_TO_KEY = {
    "webpage": "webpages",
    "document": "documents",
    "scholar": "scholars",
    "image": "images",
    "video": "videos",
    "podcast": "podcasts",
}


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(min_value, min(max_value, n))


def _strip_markdown_blockquotes(text: str) -> str:
    """Metaso /ask commonly returns Markdown blockquotes (each line prefixed with '>').

    For downstream LLM usage and for cleaner rendering in our own Markdown, we strip the prefix.
    """

    raw = _as_str(text)
    if not raw:
        return ""

    lines = raw.splitlines()
    stripped: List[str] = []
    quoted = 0
    non_empty = 0
    for ln in lines:
        s = (ln or "").rstrip()
        if s.strip():
            non_empty += 1
        t = s.lstrip()
        if t.startswith(">"):
            quoted += 1
            t = t[1:].lstrip()
        stripped.append(t)

    # Only apply if it's clearly using blockquotes.
    if non_empty and quoted / max(1, non_empty) >= 0.5:
        return "\n".join(stripped).strip()
    return raw.strip()


async def metaso_search(
    *,
    query: str,
    scope: str = "webpage",
    include_summary: bool = True,
    size: int = 10,
) -> Dict[str, Any]:
    """Search using Metaso API and return normalized results.

    Returns:
    {
      "success": bool,
      "provider": "metaso",
      "query": str,
      "scope": str,
      "include_summary": bool,
      "summary": str,
      "results": [{"title","url","snippet", ...}],
      "error": str (optional),
      "detail": str (optional)
    }
    """

    query = _as_str(query)
    if not query:
        return {"success": False, "provider": "metaso", "error": "query 不能为空", "results": []}

    api_key = _as_str(METASO_API_KEY)
    if not api_key:
        return {
            "success": False,
            "provider": "metaso",
            "error": "未配置 METASO_API_KEY（或兼容别名 METASO_API）",
            "results": [],
        }

    scope = _as_str(scope) or "webpage"
    if scope not in _SCOPE_TO_KEY:
        return {
            "success": False,
            "provider": "metaso",
            "error": f"不支持的 scope: {scope}（支持: {', '.join(sorted(_SCOPE_TO_KEY.keys()))}）",
            "results": [],
        }

    size = _clamp_int(size, default=10, min_value=1, max_value=20)
    include_summary = bool(include_summary)

    url = f"{_as_str(METASO_BASE_URL).rstrip('/')}/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "q": query,
        "scope": scope,
        "includeSummary": include_summary,
        # Metaso expects `size` as string in the official MCP server implementation.
        "size": str(size),
    }

    timeout_s = float(METASO_TIMEOUT or 30)
    timeout_s = max(5.0, min(timeout_s, 120.0))

    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.text
        except Exception:
            detail = str(exc)
        return {
            "success": False,
            "provider": "metaso",
            "query": query,
            "scope": scope,
            "include_summary": include_summary,
            "error": f"Metaso API HTTP {exc.response.status_code}",
            "detail": detail[:2000],
            "results": [],
        }
    except Exception as exc:
        return {
            "success": False,
            "provider": "metaso",
            "query": query,
            "scope": scope,
            "include_summary": include_summary,
            "error": f"Metaso API 调用失败: {exc}",
            "results": [],
        }

    # Metaso sometimes returns application-level errors as JSON with errCode/errMsg (HTTP 200).
    if isinstance(data, dict) and "errCode" in data:
        return {
            "success": False,
            "provider": "metaso",
            "query": query,
            "scope": scope,
            "include_summary": include_summary,
            "error": str(data.get("errMsg") or f"Metaso error code {data.get('errCode')}").strip(),
            "detail": "",
            "results": [],
        }

    summary = _as_str(data.get("summary")) if isinstance(data, dict) else ""
    key = _SCOPE_TO_KEY.get(scope, "webpages")
    raw_items = data.get(key, []) if isinstance(data, dict) else []

    results: List[Dict[str, Any]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = _as_str(item.get("title"))
            url_value = _as_str(item.get("link") or item.get("url") or item.get("sourceUrl"))
            snippet = _as_str(item.get("snippet") or item.get("abstract") or item.get("description"))
            result: Dict[str, Any] = {"title": title, "url": url_value, "snippet": snippet}

            # Keep a few optional fields when present; callers may ignore them.
            for k in ("displayDate", "publishDate", "date", "year", "score", "position", "authors", "venue", "doi"):
                if k in item:
                    result[k] = item.get(k)
            results.append(result)

    return {
        "success": True,
        "provider": "metaso",
        "query": query,
        "scope": scope,
        "include_summary": include_summary,
        "summary": summary,
        "results": results,
    }


async def metaso_ask(
    *,
    query: str,
    scope: str = "webpage",
    size: int = 10,
    format: str = "simple",
    model: str = "",
) -> Dict[str, Any]:
    """Ask using Metaso /ask (direct Q&A) and return normalized answer + sources.

    This is typically higher-quality for "explain concept" queries than plain /search.

    Returns (normalized):
    {
      "success": bool,
      "provider": "metaso",
      "mode": "ask",
      "query": str,
      "scope": str,
      "format": str,
      "model": str (optional),
      "answer": str,
      "sources": [{"title","link","snippet","date", ...}],
      "results": [{"title","url","snippet","date", ...}]   # alias of sources with normalized url field
    }
    """

    query = _as_str(query)
    if not query:
        return {"success": False, "provider": "metaso", "mode": "ask", "error": "query 不能为空", "results": []}

    api_key = _as_str(METASO_API_KEY)
    if not api_key:
        return {
            "success": False,
            "provider": "metaso",
            "mode": "ask",
            "error": "未配置 METASO_API_KEY（或兼容别名 METASO_API）",
            "results": [],
        }

    scope = _as_str(scope) or "webpage"
    if scope not in _SCOPE_TO_KEY:
        return {
            "success": False,
            "provider": "metaso",
            "mode": "ask",
            "error": f"不支持的 scope: {scope}（支持: {', '.join(sorted(_SCOPE_TO_KEY.keys()))}）",
            "results": [],
        }

    size = _clamp_int(size, default=10, min_value=1, max_value=20)
    format = _as_str(format) or "simple"
    model = _as_str(model)

    url = f"{_as_str(METASO_BASE_URL).rstrip('/')}/ask"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload: Dict[str, Any] = {
        "q": query,
        "scope": scope,
        "format": format,
        # Keep consistent with /search: Metaso expects `size` as string in its own implementation.
        "size": str(size),
    }
    if model:
        payload["model"] = model

    timeout_s = float(METASO_TIMEOUT or 30)
    timeout_s = max(5.0, min(timeout_s, 120.0))

    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.text
        except Exception:
            detail = str(exc)
        return {
            "success": False,
            "provider": "metaso",
            "mode": "ask",
            "query": query,
            "scope": scope,
            "format": format,
            "model": model,
            "error": f"Metaso API HTTP {exc.response.status_code}",
            "detail": detail[:2000],
            "results": [],
        }
    except Exception as exc:
        return {
            "success": False,
            "provider": "metaso",
            "mode": "ask",
            "query": query,
            "scope": scope,
            "format": format,
            "model": model,
            "error": f"Metaso API 调用失败: {exc}",
            "results": [],
        }

    if isinstance(data, dict) and "errCode" in data:
        return {
            "success": False,
            "provider": "metaso",
            "mode": "ask",
            "query": query,
            "scope": scope,
            "format": format,
            "model": model,
            "error": str(data.get("errMsg") or f"Metaso error code {data.get('errCode')}").strip(),
            "detail": "",
            "results": [],
        }

    answer = ""
    sources: List[Dict[str, Any]] = []
    credits = None

    if isinstance(data, dict):
        # format=simple returns {answer, sources, credits}
        if isinstance(data.get("answer"), str):
            answer = _strip_markdown_blockquotes(data.get("answer") or "")
        credits = data.get("credits")
        if isinstance(data.get("sources"), list):
            sources = [x for x in (data.get("sources") or []) if isinstance(x, dict)]

        # format=default returns OpenAI-ish {choices:[{message:{content}}], ...}
        if not answer and isinstance(data.get("choices"), list) and data.get("choices"):
            try:
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str):
                    answer = _strip_markdown_blockquotes(content)
            except Exception:
                answer = ""

    results: List[Dict[str, Any]] = []
    for s in sources:
        title = _as_str(s.get("title"))
        url_value = _as_str(s.get("link") or s.get("url") or s.get("sourceUrl"))
        snippet = _as_str(s.get("snippet") or s.get("abstract") or s.get("description"))
        result: Dict[str, Any] = {"title": title, "url": url_value, "snippet": snippet}
        for k in ("date", "displayDate", "publishDate", "year", "score", "position", "authors", "venue", "doi"):
            if k in s:
                result[k] = s.get(k)
        results.append(result)

    return {
        "success": True,
        "provider": "metaso",
        "mode": "ask",
        "query": query,
        "scope": scope,
        "format": format,
        "model": model,
        "answer": answer,
        "credits": credits,
        "sources": sources,
        "results": results,
    }


async def metaso_reader(*, url: str) -> Dict[str, Any]:
    """Read and extract page text using Metaso /reader API."""

    url_value = _as_str(url)
    if not url_value:
        return {"success": False, "provider": "metaso", "error": "url 不能为空"}

    api_key = _as_str(METASO_API_KEY)
    if not api_key:
        return {
            "success": False,
            "provider": "metaso",
            "error": "未配置 METASO_API_KEY（或兼容别名 METASO_API）",
        }

    endpoint = f"{_as_str(METASO_BASE_URL).rstrip('/')}/reader"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/plain",
    }
    payload = {"url": url_value}

    timeout_s = float(METASO_TIMEOUT or 30)
    timeout_s = max(5.0, min(timeout_s, 120.0))

    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            text = resp.text
    except Exception as exc:
        return {"success": False, "provider": "metaso", "url": url_value, "error": str(exc)}

    # /reader may also return JSON errors (HTTP 200) when key is invalid, etc.
    # We treat those as failure so callers can fall back.
    if text.strip().startswith("{") and ("errCode" in text and "errMsg" in text):
        try:
            obj = resp.json()
            if isinstance(obj, dict) and "errCode" in obj:
                return {
                    "success": False,
                    "provider": "metaso",
                    "url": url_value,
                    "error": str(obj.get("errMsg") or f"Metaso error code {obj.get('errCode')}").strip(),
                }
        except Exception:
            logger.debug("metaso_error_payload_parse_failed", exc_info=True)

    return {"success": True, "provider": "metaso", "url": url_value, "text": text}
