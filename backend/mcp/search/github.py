"""GitHub search utility.

This module is used by the self-study materials agent to discover high-signal
learning resources on GitHub (notes, tutorials, code examples).

Notes:
- Uses GitHub's public REST API (search/repositories).
- Optional authentication via `GITHUB_TOKEN` to increase rate limits.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Dict, List

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import API_TIMEOUT

logger = get_logger(__name__)

_GITHUB_API_BASE = (os.getenv("GITHUB_API_BASE_URL") or "https://api.github.com").rstrip("/")
_GITHUB_TOKEN = (os.getenv("GITHUB_TOKEN") or "").strip()


def _clip(text: str, *, max_len: int) -> str:
    if max_len <= 0:
        return ""
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _build_headers(*, token: str) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "study_ai/1.0 (github_search)",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def github_fetch_readme(
    full_name: str,
    *,
    token: str = "",
    max_chars: int = 4000,
) -> Dict[str, Any]:
    """Fetch repository README as raw text (best-effort)."""

    repo = (full_name or "").strip()
    if not repo or "/" not in repo:
        return {"success": False, "error": "invalid repo full_name", "provider": "github"}

    effective_token = (token or "").strip() or _GITHUB_TOKEN
    timeout = float(API_TIMEOUT or 120)

    headers = _build_headers(token=effective_token)
    # Raw readme content
    headers["Accept"] = "application/vnd.github.raw"

    retry_statuses = {408, 429, 500, 502, 503, 504}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=min(max(timeout, 10.0), 60.0),
                headers=headers,
                follow_redirects=True,
            ) as client:
                resp = await client.get(f"{_GITHUB_API_BASE}/repos/{repo}/readme")

            if resp.status_code in retry_statuses and attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue

            if resp.status_code in {401, 403, 404}:
                return {
                    "success": False,
                    "provider": "github",
                    "error": f"readme_unavailable_status_{resp.status_code}",
                }

            resp.raise_for_status()
            text = (resp.text or "").strip()
            return {"success": True, "provider": "github", "full_name": repo, "readme": _clip(text, max_len=max_chars)}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            return {"success": False, "provider": "github", "full_name": repo, "error": str(exc)}


async def github_search_repositories(
    query: str,
    *,
    limit: int = 5,
    sort: str = "stars",
    order: str = "desc",
    token: str = "",
) -> Dict[str, Any]:
    """Search repositories by query.

    Returns:
      {
        "success": bool,
        "query": str,
        "results": [{...}],
        "total_count": int,
        "provider": "github",
        "note": str (optional),
        "error": str (optional)
      }
    """

    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "query 不能为空", "provider": "github"}

    limit = int(limit or 5)
    limit = max(1, min(limit, 20))

    sort = (sort or "stars").strip()
    if sort not in {"stars", "forks", "help-wanted-issues", "updated"}:
        sort = "stars"

    order = (order or "desc").strip().lower()
    if order not in {"asc", "desc"}:
        order = "desc"

    effective_token = (token or "").strip() or _GITHUB_TOKEN
    timeout = float(API_TIMEOUT or 120)

    params = {
        "q": q,
        "per_page": limit,
        "sort": sort,
        "order": order,
    }

    note = ""
    if not effective_token:
        note = "未配置 GITHUB_TOKEN，可能触发更严格的 GitHub API 速率限制。"

    retry_statuses = {408, 429, 500, 502, 503, 504}
    data: Any = {}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=min(max(timeout, 10.0), 60.0),
                headers=_build_headers(token=effective_token),
                follow_redirects=True,
            ) as client:
                resp = await client.get(f"{_GITHUB_API_BASE}/search/repositories", params=params)

            if resp.status_code in retry_statuses and attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue

            if resp.status_code in {401, 403}:
                # 403 can also mean rate limit; return a readable message.
                msg = f"GitHub API rejected request (status={resp.status_code})."
                try:
                    data_err = resp.json()
                    if isinstance(data_err, dict) and data_err.get("message"):
                        msg = str(data_err.get("message"))
                except ValueError:
                    logger.debug("github_api_error_payload_parse_failed", exc_info=True)
                return {"success": False, "query": q, "provider": "github", "error": msg, "note": note}

            resp.raise_for_status()
            data = resp.json()
            break
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if attempt < 2:
                await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                continue
            return {"success": False, "query": q, "provider": "github", "error": str(exc), "note": note}

    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []

    results: List[Dict[str, Any]] = []
    for it in items[:limit]:
        if not isinstance(it, dict):
            continue
        results.append(
            {
                "full_name": str(it.get("full_name") or "").strip(),
                "url": str(it.get("html_url") or "").strip(),
                "description": _clip(str(it.get("description") or ""), max_len=240),
                "stars": int(it.get("stargazers_count") or 0),
                "language": str(it.get("language") or "").strip(),
                "updated_at": str(it.get("updated_at") or "").strip(),
                "default_branch": str(it.get("default_branch") or "").strip(),
            }
        )

    out: Dict[str, Any] = {
        "success": True,
        "query": q,
        "results": results,
        "total_count": int(data.get("total_count") or 0) if isinstance(data, dict) else 0,
        "provider": "github",
    }
    if note:
        out["note"] = note
    return out
