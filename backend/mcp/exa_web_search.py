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
    Search the web using Exa AI.
    
    Args:
        query: The search query
        num_results: Number of results to return (max 10)
        use_autoprompt: Whether to use Exa's autoprompt feature
        type: Search type - neural, keyword, or auto
        category: Filter by category (e.g., "news", "research paper")
        include_domains: List of domains to include
        exclude_domains: List of domains to exclude
        start_crawl_date: Filter by crawl date (ISO format)
        end_crawl_date: Filter by crawl date (ISO format)
        start_published_date: Filter by published date
        end_published_date: Filter by published date
        include_text: Whether to include text content
        text_max_length: Max length of text content
    
    Returns:
        Dict with search results
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
    Find similar pages to a given URL using Exa AI.
    
    Args:
        url: The URL to find similar pages for
        num_results: Number of results to return
        include_domains: List of domains to include
        exclude_domains: List of domains to exclude
        exclude_source_domain: Whether to exclude the source domain
    
    Returns:
        Dict with similar page results
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
