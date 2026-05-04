"""StackExchange search utility.

Used by the self-study materials agent to fetch high-quality Q&A explanations
from StackExchange network sites (e.g. math.stackexchange.com).

API docs: https://api.stackexchange.com/
Auth:
- Optional `STACKEXCHANGE_KEY` for higher quota.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup

from backend.core.logging_utils import get_logger
from backend.core.settings import API_TIMEOUT

logger = get_logger(__name__)

_STACKEXCHANGE_API_BASE = (os.getenv("STACKEXCHANGE_API_BASE_URL") or "https://api.stackexchange.com/2.3").rstrip("/")
_STACKEXCHANGE_KEY = (os.getenv("STACKEXCHANGE_KEY") or "").strip()


def _clip(text: str, *, max_len: int) -> str:
    if max_len <= 0:
        return ""
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _html_to_text(html: str) -> str:
    raw = (html or "").strip()
    if not raw:
        return ""
    try:
        soup = BeautifulSoup(raw, "lxml")
        # Remove scripts/styles.
        for tag in soup(["script", "style"]):
            try:
                tag.decompose()
            except Exception:
                logger.warning("stackexchange_html_sanitize_failed", exc_info=True)
        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
    except Exception:
        logger.warning("stackexchange_html_parse_failed", exc_info=True)
        return re.sub(r"<[^>]+>", "", raw).strip()


async def stackexchange_search(
    query: str,
    *,
    site: str,
    limit: int = 5,
    sort: str = "votes",
    order: str = "desc",
    include_answers: bool = True,
    max_question_chars: int = 2600,
    max_answer_chars: int = 2600,
) -> Dict[str, Any]:
    """Search StackExchange and optionally fetch top answers.

    Returns:
      {
        "success": bool,
        "query": str,
        "site": str,
        "results": [{...}],
        "provider": "stackexchange",
        "error": str (optional)
      }
    """

    q = (query or "").strip()
    if not q:
        return {"success": False, "error": "query 不能为空", "provider": "stackexchange"}

    s = (site or "").strip()
    if not s:
        return {"success": False, "error": "site 不能为空（例如 math.stackexchange）", "provider": "stackexchange"}

    limit = int(limit or 5)
    limit = max(1, min(limit, 10))

    sort = (sort or "votes").strip().lower()
    if sort not in {"relevance", "votes", "creation", "activity"}:
        sort = "votes"

    order = (order or "desc").strip().lower()
    if order not in {"asc", "desc"}:
        order = "desc"

    timeout = float(API_TIMEOUT or 120)

    params = {
        "q": q,
        "site": s,
        "pagesize": limit,
        "order": order,
        "sort": sort,
        # Include body as HTML so we can extract text locally.
        "filter": "withbody",
    }
    if _STACKEXCHANGE_KEY:
        params["key"] = _STACKEXCHANGE_KEY

    retry_statuses = {408, 429, 500, 502, 503, 504}

    try:
        async with httpx.AsyncClient(
            timeout=min(max(timeout, 10.0), 60.0),
            headers={"User-Agent": "study_ai/1.0 (stackexchange_search)"},
            follow_redirects=True,
        ) as client:
            data: Any = {}
            for attempt in range(3):
                try:
                    resp = await client.get(f"{_STACKEXCHANGE_API_BASE}/search/advanced", params=params)
                    if resp.status_code in retry_statuses and attempt < 2:
                        await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                        continue
                    resp.raise_for_status()
                    payload = resp.json()
                    data = payload if isinstance(payload, dict) else {}
                    break
                except (httpx.HTTPError, ValueError, TypeError):
                    if attempt < 2:
                        await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                        continue
                    raise

            items = data.get("items") if isinstance(data.get("items"), list) else []
            questions: List[Dict[str, Any]] = [it for it in items if isinstance(it, dict)]

            qids: List[int] = []
            for it in questions:
                try:
                    qid = int(it.get("question_id") or 0)
                except (TypeError, ValueError):
                    qid = 0
                if qid > 0:
                    qids.append(qid)

            answers_by_qid: Dict[int, Dict[str, Any]] = {}
            if include_answers and qids:
                ans_params = {
                    "site": s,
                    "pagesize": 1,
                    "order": "desc",
                    "sort": "votes",
                    "filter": "withbody",
                }
                if _STACKEXCHANGE_KEY:
                    ans_params["key"] = _STACKEXCHANGE_KEY
                ids = ";".join([str(x) for x in qids[: min(len(qids), 10)]])

                ans_data: Any = {}
                for attempt in range(3):
                    try:
                        ans_resp = await client.get(
                            f"{_STACKEXCHANGE_API_BASE}/questions/{ids}/answers",
                            params=ans_params,
                        )
                        if ans_resp.status_code in retry_statuses and attempt < 2:
                            await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                            continue
                        if ans_resp.status_code != 200:
                            break
                        payload = ans_resp.json()
                        ans_data = payload if isinstance(payload, dict) else {}
                        break
                    except (httpx.HTTPError, ValueError, TypeError):
                        if attempt < 2:
                            await asyncio.sleep(min(6.0, (2**attempt) * 0.8 + random.random() * 0.6))
                            continue
                        break

                for a in (ans_data.get("items") or [])[:50]:
                    if not isinstance(a, dict):
                        continue
                    try:
                        qid = int(a.get("question_id") or 0)
                    except (TypeError, ValueError):
                        qid = 0
                    if qid <= 0:
                        continue
                    if qid in answers_by_qid:
                        continue
                    answers_by_qid[qid] = a

            results: List[Dict[str, Any]] = []
            for it in questions[:limit]:
                title = str(it.get("title") or "").strip()
                url = str(it.get("link") or "").strip()
                try:
                    score = int(it.get("score") or 0)
                except (TypeError, ValueError):
                    score = 0
                tags = it.get("tags") if isinstance(it.get("tags"), list) else []
                tags = [str(t) for t in tags if str(t).strip()][:12]
                is_answered = bool(it.get("is_answered") is True)
                try:
                    qid = int(it.get("question_id") or 0)
                except (TypeError, ValueError):
                    qid = 0

                question_text = _clip(_html_to_text(str(it.get("body") or "")), max_len=max_question_chars)

                top_answer_text = ""
                if include_answers and qid > 0 and qid in answers_by_qid:
                    top_answer_text = _clip(
                        _html_to_text(str(answers_by_qid[qid].get("body") or "")),
                        max_len=max_answer_chars,
                    )

                results.append(
                    {
                        "question_id": qid,
                        "title": title,
                        "url": url,
                        "score": score,
                        "tags": tags,
                        "is_answered": is_answered,
                        "question_text": question_text,
                        "top_answer_text": top_answer_text,
                    }
                )

            return {
                "success": True,
                "query": q,
                "site": s,
                "results": results,
                "provider": "stackexchange",
            }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"success": False, "query": q, "site": s, "provider": "stackexchange", "error": str(exc)}
