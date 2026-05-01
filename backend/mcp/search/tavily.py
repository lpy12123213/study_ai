"""Tavily web search integration for MCP."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from backend.core.settings import load_project_dotenv

load_project_dotenv(override=False)

TAVILY_API_KEY = (os.getenv("TAVILY_API_KEY") or "").strip()
TAVILY_BASE_URL = (os.getenv("TAVILY_BASE_URL") or "https://api.tavily.com").rstrip("/")
try:
    TAVILY_TIMEOUT = int(os.getenv("TAVILY_TIMEOUT") or "60")
except ValueError:
    TAVILY_TIMEOUT = 60


async def tavily_search(
    query: str,
    max_results: int = 10,
    search_depth: str = "basic",
    include_answer: bool = False,
    include_raw_content: bool = False,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    topic: str = "general",
    days: Optional[int] = None,
    time_range: str = "",
    start_date: str = "",
    end_date: str = "",
) -> Dict[str, Any]:
    """使用 Tavily Search API 搜索网页。

    Args:
        query: 搜索查询字符串
        max_results: 返回结果数量（最多 10 个）
        search_depth: 搜索深度 - "basic"（快速）或 "advanced"（深度）
        include_answer: 是否返回 AI 生成的答案摘要
        include_raw_content: 是否包含原始页面内容
        include_domains: 要包含的域名列表
        exclude_domains: 要排除的域名列表
        topic: 搜索类别 - "general"、"news" 或 "finance"
        days: news topic 下向前回溯天数
        time_range: general topic 下的时间范围（day/week/month/year 或 d/w/m/y）
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        包含搜索结果的字典
    """
    if not TAVILY_API_KEY:
        return {
            "success": False,
            "provider": "tavily",
            "query": query,
            "error": "Tavily API key not configured",
            "results": [],
        }

    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "query": query,
        "max_results": min(max_results, 20),
        "search_depth": search_depth,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
    }

    topic = str(topic or "general").strip().lower()
    if topic in {"general", "news", "finance"}:
        payload["topic"] = topic
    if days is not None:
        payload["days"] = max(1, int(days or 1))
    if time_range:
        payload["time_range"] = str(time_range).strip()
    if start_date:
        payload["start_date"] = str(start_date).strip()
    if end_date:
        payload["end_date"] = str(end_date).strip()
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    try:
        async with httpx.AsyncClient(timeout=float(TAVILY_TIMEOUT or 60)) as client:
            response = await client.post(
                f"{TAVILY_BASE_URL}/search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for r in data.get("results", []):
                content = str(r.get("content") or "").strip()
                raw_content = str(r.get("raw_content") or "").strip()
                text = raw_content or content
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "text": text,
                        "snippet": content[:500] if content else "",
                        "score": r.get("score", 0),
                        "published_date": r.get("published_date") or r.get("publishedDate"),
                    }
                )

            out: Dict[str, Any] = {
                "success": True,
                "provider": "tavily",
                "query": query,
                "results": results,
            }

            answer = str(data.get("answer") or "").strip()
            if answer:
                out["answer"] = answer

            return out
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "provider": "tavily",
            "query": query,
            "error": f"Tavily API error: {e.response.status_code}",
            "results": [],
        }
    except Exception as e:
        return {
            "success": False,
            "provider": "tavily",
            "query": query,
            "error": f"Tavily search failed: {str(e)}",
            "results": [],
        }
