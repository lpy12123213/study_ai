"""Exa web search integration for MCP."""

from __future__ import annotations

import os
import httpx
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv(override=False)

# NOTE: `EXA_API` is a legacy alias kept for compatibility.
EXA_API_KEY = (os.getenv("EXA_API_KEY") or os.getenv("EXA_API") or "").strip()
EXA_BASE_URL = (os.getenv("EXA_BASE_URL") or "https://api.exa.ai").rstrip("/")


async def exa_answer(
    query: str,
    num_results: int = 5,
    include_text: bool = True,
    text_max_length: int = 1000,
) -> Dict[str, Any]:
    """
    使用 Exa Answer API 提出问题并获取带有引用的 AI 生成答案。

    Args:
        query: 要回答的问题
        num_results: 使用的源结果数量（最多 10 个）
        include_text: 是否在引用中包含源文本
        text_max_length: 每个引用文本内容的最大长度

    Returns:
        包含答案和引用的字典
    """
    if not EXA_API_KEY:
        return {
            "error": "Exa API key not configured",
            "answer": "",
            "citations": [],
        }

    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "query": query,
        "numResults": min(num_results, 10),
    }

    if include_text:
        payload["text"] = True

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{EXA_BASE_URL}/answer",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            citations = []
            for c in data.get("citations", []):
                citations.append({
                    "title": c.get("title", ""),
                    "url": c.get("url", ""),
                    "text": (c.get("text", "") or "")[:text_max_length],
                    "published_date": c.get("publishedDate"),
                })

            return {
                "answer": data.get("answer", ""),
                "citations": citations,
                "success": True,
            }
    except httpx.HTTPStatusError as e:
        return {
            "error": f"Exa Answer API error: {e.response.status_code}",
            "answer": "",
            "citations": [],
        }
    except Exception as e:
        return {
            "error": f"Exa Answer failed: {str(e)}",
            "answer": "",
            "citations": [],
        }


async def exa_search(
    query: str,
    num_results: int = 10,
    use_autoprompt: bool = True,
    type: str = "neural",  # neural, keyword, or auto
    category: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    start_crawl_date: Optional[str] = None,
    end_crawl_date: Optional[str] = None,
    start_published_date: Optional[str] = None,
    end_published_date: Optional[str] = None,
    include_text: bool = True,
    text_max_length: int = 1000,
) -> Dict[str, Any]:
    """
    使用 Exa AI 搜索网页。
    
    Args:
        query: 搜索查询字符串
        num_results: 返回结果数量（最多 10 个）
        use_autoprompt: 是否使用 Exa 的自动提示功能
        type: 搜索类型 - neural（神经搜索）、keyword（关键词搜索）或 auto（自动）
        category: 按类别筛选（如 "news"、"research paper"）
        include_domains: 要包含的域名列表
        exclude_domains: 要排除的域名列表
        start_crawl_date: 按爬取日期筛选（ISO 格式）
        end_crawl_date: 按爬取日期筛选（ISO 格式）
        start_published_date: 按发布日期筛选
        end_published_date: 按发布日期筛选
        include_text: 是否包含文本内容
        text_max_length: 文本内容最大长度
    
    Returns:
        包含搜索结果的字典
    """
    if not EXA_API_KEY:
        return {
            "error": "Exa API key not configured",
            "results": [],
        }
    
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    
    payload: Dict[str, Any] = {
        "query": query,
        "numResults": min(num_results, 10),
        "useAutoprompt": use_autoprompt,
        "type": type,
    }
    
    if category:
        payload["category"] = category
    if include_domains:
        payload["includeDomains"] = include_domains
    if exclude_domains:
        payload["excludeDomains"] = exclude_domains
    if start_crawl_date:
        payload["startCrawlDate"] = start_crawl_date
    if end_crawl_date:
        payload["endCrawlDate"] = end_crawl_date
    if start_published_date:
        payload["startPublishedDate"] = start_published_date
    if end_published_date:
        payload["endPublishedDate"] = end_published_date
    
    # Contents configuration
    if include_text:
        payload["contents"] = {
            "text": {"maxCharacters": text_max_length}
        }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{EXA_BASE_URL}/search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            return {
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "score": r.get("score", 0),
                        "published_date": r.get("publishedDate"),
                        "text": r.get("text", ""),
                    }
                    for r in data.get("results", [])
                ],
                "autoprompt_string": data.get("autopromptString"),
            }
    except httpx.HTTPStatusError as e:
        return {
            "error": f"Exa API error: {e.response.status_code}",
            "results": [],
        }
    except Exception as e:
        return {
            "error": f"Exa search failed: {str(e)}",
            "results": [],
        }


async def exa_find_similar(
    url: str,
    num_results: int = 10,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    exclude_source_domain: bool = True,
) -> Dict[str, Any]:
    """
    使用 Exa AI 查找与给定 URL 相似的页面。
    
    Args:
        url: 要查找相似页面的 URL
        num_results: 返回的结果数量
        include_domains: 要包含的域名列表
        exclude_domains: 要排除的域名列表
        exclude_source_domain: 是否排除源域名
    
    Returns:
        包含相似页面结果的字典
    """
    if not EXA_API_KEY:
        return {
            "error": "Exa API key not configured",
            "results": [],
        }
    
    headers = {
        "x-api-key": EXA_API_KEY,
        "Content-Type": "application/json",
    }
    
    payload: Dict[str, Any] = {
        "url": url,
        "numResults": min(num_results, 10),
        "excludeSourceDomain": exclude_source_domain,
    }
    
    if include_domains:
        payload["includeDomains"] = include_domains
    if exclude_domains:
        payload["excludeDomains"] = exclude_domains
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{EXA_BASE_URL}/findSimilar",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            return {
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "score": r.get("score", 0),
                    }
                    for r in data.get("results", [])
                ],
            }
    except Exception as e:
        return {
            "error": f"Exa find similar failed: {str(e)}",
            "results": [],
        }
