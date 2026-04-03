"""MCP Server implementation for tool registration."""

from __future__ import annotations

import json
import sys
from typing import Any, Awaitable, Callable, Dict, List

# Tool registry
_tools: Dict[str, Dict[str, Any]] = {}
_tool_handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}


def register_tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    handler: Callable[..., Awaitable[Any]],
) -> None:
    """Register a tool with the MCP server."""
    _tools[name] = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
    _tool_handlers[name] = handler


def get_tools() -> List[Dict[str, Any]]:
    """Get all registered tools in OpenAI tool format."""
    return list(_tools.values())


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Get tool definitions for API responses."""
    return [
        {
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "parameters": tool["function"]["parameters"],
        }
        for tool in _tools.values()
    ]


async def execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute a registered tool."""
    if name not in _tool_handlers:
        raise ValueError(f"Unknown tool: {name}")

    handler = _tool_handlers[name]
    return await handler(**arguments)


async def handle_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """Handle a tool call from an AI model."""
    name = tool_call.get("function", {}).get("name", "")
    arguments_str = tool_call.get("function", {}).get("arguments", "{}")

    try:
        arguments = json.loads(arguments_str)
    except json.JSONDecodeError:
        return {
            "tool_call_id": tool_call.get("id", ""),
            "output": json.dumps({"error": "Invalid arguments JSON"}),
        }

    try:
        result = await execute_tool(name, arguments)
        return {
            "tool_call_id": tool_call.get("id", ""),
            "output": json.dumps(result) if not isinstance(result, str) else result,
        }
    except Exception as e:
        return {
            "tool_call_id": tool_call.get("id", ""),
            "output": json.dumps({"error": str(e)}),
        }


# Register default tools
def _register_default_tools():
    """Register default MCP tools."""
    from backend.mcp.search.bigmodel import bigmodel_web_search
    from backend.mcp.search.exa import exa_search
    from backend.mcp.tools.python_scientific_compute import SCIENTIFIC_COMPUTE_INPUT_SCHEMA, python_scientific_compute
    from backend.mcp.tools.reviewer import review_question

    register_tool(
        name="web_search",
        description="Search the web for information",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=lambda query, max_results=5: bigmodel_web_search(query, max_results=max_results),
    )

    register_tool(
        name="exa_search",
        description="Search the web using Exa AI for high-quality results",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        handler=lambda query, num_results=10: exa_search(query, num_results=num_results),
    )

    register_tool(
        name="review_question",
        description="Review an exam question for quality and accuracy",
        parameters={
            "type": "object",
            "properties": {
                "stem": {
                    "type": "string",
                    "description": "The question text",
                },
                "answer": {
                    "type": "string",
                    "description": "The answer (optional)",
                },
                "analysis": {
                    "type": "string",
                    "description": "The explanation/analysis (optional)",
                },
                "subject": {
                    "type": "string",
                    "description": "The subject area (optional)",
                },
            },
            "required": ["stem"],
        },
        handler=review_question,
    )

    register_tool(
        name="python_scientific_compute",
        description="Run restricted Python scientific computation for math verification and example generation",
        parameters=SCIENTIFIC_COMPUTE_INPUT_SCHEMA,
        handler=python_scientific_compute,
    )


# Initialize default tools on import
try:
    _register_default_tools()
except ImportError:
    # Tools may not be available in all environments
    pass


def _alias_legacy_module_names() -> None:
    """
    Back-compat aliases for callers that still import the old flat module paths, e.g.
    `backend.mcp.server` after the directory regrouping.

    NOTE: This does NOT help `python -m backend.mcp.stdio_server` because `-m` needs a spec
    on disk. For `-m`, we keep a thin wrapper module at the legacy path.
    """

    # Only alias the ones that were historically imported as "backend.mcp.<name>".
    alias_map = {
        "server": __name__,
    }
    pkg = "backend.mcp"
    for legacy, target in alias_map.items():
        sys.modules.setdefault(f"{pkg}.{legacy}", sys.modules[target])


_alias_legacy_module_names()
