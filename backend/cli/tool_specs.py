"""OpenAI-style tool specs reused by ``backend.cli.question_generate``.

Extracted from the (long) CLI module so the tool descriptors live in one
focused place; the CLI now imports these directly. The shapes match what
``chat_completion`` accepts for the ``tools`` argument.
"""

from __future__ import annotations

from typing import Any, Dict


def mcp_web_search_tool_spec() -> Dict[str, Any]:
    """Schema for the ``mcp_web_search`` tool (Tavily / Exa / Bigmodel).

    The LLM uses this to decide when/how to invoke web search for question
    generation references. Recency days only apply in ``trending`` mode.
    """

    return {
        "type": "function",
        "function": {
            "name": "mcp_web_search",
            "description": "【联网搜索】搜索互联网获取出题素材。返回结构化搜索结果列表（含 url）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词/问题"},
                    "limit": {"type": "integer", "description": "返回条数(1-10)", "default": 5},
                    "provider": {
                        "type": "string",
                        "enum": ["auto", "tavily", "exa", "bigmodel"],
                        "description": "搜索提供方：auto(优先 tavily) | tavily | exa | bigmodel",
                        "default": "auto",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["trending", "patterns"],
                        "description": "trending=时兴素材；patterns=真题规律",
                        "default": "trending",
                    },
                    "recency_days": {
                        "type": "integer",
                        "description": "trending 模式下按发布日期近 N 天筛选（tavily/exa 生效）",
                        "default": 180,
                    },
                },
                "required": ["query"],
            },
        },
    }


def python_scientific_compute_tool_spec() -> Dict[str, Any]:
    """Schema for the sandboxed Python compute tool.

    Defers to :func:`backend.integrations.mcp.tools.python_scientific_compute.openai_tool_spec`
    so the CLI and the MCP server share a single source of truth.
    """

    from backend.integrations.mcp.tools.python_scientific_compute import openai_tool_spec

    return openai_tool_spec()


__all__ = ["mcp_web_search_tool_spec", "python_scientific_compute_tool_spec"]
