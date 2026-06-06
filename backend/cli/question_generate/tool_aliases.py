"""Compatibility aliases for question-generation CLI helper functions."""

from __future__ import annotations

from typing import Any, Dict, List


def _mcp_web_search_tool_spec() -> Dict[str, Any]:
    """Backwards-compatible alias for the public tool spec helper."""

    from backend.cli.tool_specs import mcp_web_search_tool_spec

    return mcp_web_search_tool_spec()


def _python_scientific_compute_tool_spec() -> Dict[str, Any]:
    """Backwards-compatible alias; see :mod:`backend.cli.tool_specs`."""

    from backend.cli.tool_specs import python_scientific_compute_tool_spec

    return python_scientific_compute_tool_spec()


def _fallback_search_markdown(*, query: str, tool_result: Dict[str, Any]) -> str:
    """Backwards-compatible alias; see :mod:`backend.cli.fallback_markdown`."""

    from backend.cli.fallback_markdown import fallback_search_markdown

    return fallback_search_markdown(query=query, tool_result=tool_result)


def _fallback_material_markdown(*, query: str, tool_results: List[Dict[str, Any]]) -> str:
    """Backwards-compatible alias; see :mod:`backend.cli.fallback_markdown`."""

    from backend.cli.fallback_markdown import fallback_material_markdown

    return fallback_material_markdown(query=query, tool_results=tool_results)


async def _exec_python_scientific_compute_tool(
    *,
    code: str,
    purpose: str,
    timeout_seconds: int,
) -> Dict[str, Any]:
    from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute

    return await python_scientific_compute(
        code=str(code or "").strip(),
        purpose=str(purpose or "").strip(),
        timeout_seconds=int(timeout_seconds or 5),
    )
