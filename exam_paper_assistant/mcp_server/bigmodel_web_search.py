"""
BigModel Web Search (MCP Broker) client.

This module calls Zhipu BigModel's OpenAPI chat/completions endpoint and lets
the model use the official MCP broker "web-search" server (SSE) to perform
internet search.

Do NOT hardcode secrets. Configure via environment variables:
- ZHIPU_API_KEY (required)
- ZHIPU_BASE_URL (optional, default: https://open.bigmodel.cn/api/paas/v4)
- ZHIPU_MODEL (optional, default: glm-4.5)
- ZHIPU_TIMEOUT (optional, default: 60 seconds)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from core.settings import ZHIPU_API_KEY, ZHIPU_BASE_URL, ZHIPU_MODEL, ZHIPU_TIMEOUT

DEFAULT_ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_ZHIPU_MODEL = "glm-4.5"
DEFAULT_TIMEOUT_SECONDS = 60

BIGMODEL_WEB_SEARCH_SSE_URL = (
    "https://open.bigmodel.cn/api/mcp-broker/proxy/web-search/sse"
)

def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Remove leading ```lang and trailing ```
    first_newline = stripped.find("\n")
    if first_newline != -1:
        stripped = stripped[first_newline + 1 :]
    if stripped.endswith("```"):
        stripped = stripped[: -3]
    return stripped.strip()


def _extract_json(text: str) -> Optional[Any]:
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]

    left_brace = cleaned.find("{")
    right_brace = cleaned.rfind("}")
    if 0 <= left_brace < right_brace:
        candidates.append(cleaned[left_brace : right_brace + 1])

    left_bracket = cleaned.find("[")
    right_bracket = cleaned.rfind("]")
    if 0 <= left_bracket < right_bracket:
        candidates.append(cleaned[left_bracket : right_bracket + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


async def web_search_with_bigmodel_mcp(
    query: str,
    limit: int = 5,
    model: str = "",
) -> Dict[str, Any]:
    """
    Web search via BigModel's MCP broker (web-search).

    Returns a structured dict:
    {
      "success": bool,
      "query": str,
      "results": [...],
      "raw": str (optional),
      "provider": "zhipu-bigmodel-mcp-web-search",
      "model": "glm-4.5"
    }
    """
    query = (query or "").strip()
    if not query:
        return {"success": False, "error": "query 不能为空", "provider": "zhipu-bigmodel-mcp-web-search"}

    limit = int(limit or 5)
    limit = max(1, min(limit, 10))

    api_key = (ZHIPU_API_KEY or "").strip()
    if not api_key:
        return {
            "success": False,
            "error": "未配置 ZHIPU_API_KEY，请在 exam_paper_assistant/.env 中设置后重试",
            "provider": "zhipu-bigmodel-mcp-web-search",
        }

    base_url = (ZHIPU_BASE_URL or DEFAULT_ZHIPU_BASE_URL).rstrip("/")
    timeout_seconds = int(ZHIPU_TIMEOUT or DEFAULT_TIMEOUT_SECONDS)
    model_name = (model or ZHIPU_MODEL or DEFAULT_ZHIPU_MODEL).strip() or DEFAULT_ZHIPU_MODEL

    # Ask the model to use web-search tool and output strict JSON.
    prompt = f"""你是一个联网搜索助手，请使用 web-search 工具检索互联网信息。

搜索查询：{query}

要求：
1) 返回前 {limit} 条结果
2) 仅输出 JSON，不要输出 Markdown，不要输出任何解释文本
3) JSON 格式固定为：
{{
  "results": [
    {{
      "title": "...",
      "url": "...",
      "snippet": "..."
    }}
  ]
}}
"""

    request_body = {
        "model": model_name,
        "stream": False,
        "do_sample": False,
        "temperature": 0.2,
        "top_p": 0.95,
        "response_format": {"type": "text"},
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {
                "type": "mcp",
                "mcp": {
                    "transport_type": "sse",
                    "server_label": "web-search",
                    "server_url": BIGMODEL_WEB_SEARCH_SSE_URL,
                    "headers": {"Authorization": f"Bearer {api_key}"},
                },
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{base_url}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=request_body)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.text
        except Exception:
            detail = str(exc)
        return {
            "success": False,
            "error": f"BigModel API 请求失败: {exc.response.status_code}",
            "detail": detail[:2000],
            "provider": "zhipu-bigmodel-mcp-web-search",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"BigModel API 调用异常: {exc}",
            "provider": "zhipu-bigmodel-mcp-web-search",
        }

    content = ""
    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except Exception:
        content = json.dumps(payload, ensure_ascii=False)

    parsed = _extract_json(content)
    results: Any = []
    if isinstance(parsed, dict):
        results = parsed.get("results", parsed)
    elif isinstance(parsed, list):
        results = parsed

    return {
        "success": True,
        "query": query,
        "limit": limit,
        "results": results,
        "raw": content if not parsed else "",
        "provider": "zhipu-bigmodel-mcp-web-search",
        "model": model_name,
    }
