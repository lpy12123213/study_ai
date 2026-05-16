from __future__ import annotations

import httpx

from backend.core.http_fetch import get_shared_fetch_http_client


async def get_mcp_search_http_client() -> httpx.AsyncClient:
    return await get_shared_fetch_http_client()
