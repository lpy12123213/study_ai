"""Fallback Markdown rendering for MCP tool results in the CLI generator.

When the LLM declines (or fails) to format the search/compute output for the
question-generation pipeline we synthesise a deterministic Markdown summary
instead. The previous logic lived inline in
``backend/cli/question_generate.py``; pulling it out keeps the CLI module
focused on the agent loop while letting unit tests cover the formatting in
isolation.
"""

from __future__ import annotations

from typing import Any, Dict, List


def fallback_search_markdown(*, query: str, tool_result: Dict[str, Any]) -> str:
    """Return a human-readable Markdown digest for a single ``mcp_web_search`` result."""

    provider = str(tool_result.get("provider") or "").strip()
    parts: List[str] = []
    parts.append("# Web Search (MCP)\n")
    parts.append(f"- query: {str(query or '').strip()}\n")
    if provider:
        parts.append(f"- provider: {provider}\n")
    if str(tool_result.get("mode") or "").strip():
        parts.append(f"- mode: {str(tool_result.get('mode') or '').strip()}\n")
    if tool_result.get("recency_days"):
        parts.append(f"- recency_days: {tool_result.get('recency_days')}\n")
    if str(tool_result.get("model") or "").strip():
        parts.append(f"- model: {str(tool_result.get('model') or '').strip()}\n")
    parts.append("\n")

    results = tool_result.get("results") if isinstance(tool_result.get("results"), list) else []
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        published = str(item.get("published_date") or "").strip()
        line = f"- {title}" if title else "- (no title)"
        if url:
            line += f"\n  {url}"
        if published:
            line += f"\n  published: {published}"
        if snippet:
            line += f"\n  {snippet}"
        parts.append(line + "\n")

    return "\n".join(parts).strip()


def fallback_material_markdown(*, query: str, tool_results: List[Dict[str, Any]]) -> str:
    """Aggregate any number of MCP tool results into one Markdown block."""

    parts: List[str] = []
    parts.append("# AI Tool Materials\n")
    parts.append(f"- query: {str(query or '').strip()}\n\n")

    for item in tool_results[:12]:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool_name") or "").strip() or "unknown_tool"
        if tool_name == "mcp_web_search":
            parts.append(f"## {tool_name}\n\n")
            parts.append(fallback_search_markdown(query=query, tool_result=item) + "\n\n")
            continue

        parts.append(f"## {tool_name}\n\n")
        if str(item.get("purpose") or "").strip():
            parts.append(f"- purpose: {str(item.get('purpose') or '').strip()}\n")
        if str(item.get("result_type") or "").strip():
            parts.append(f"- result_type: {str(item.get('result_type') or '').strip()}\n")
        if str(item.get("result_repr") or "").strip():
            parts.append(f"- result: {str(item.get('result_repr') or '').strip()}\n")
        if str(item.get("stdout") or "").strip():
            parts.append(f"- stdout: {str(item.get('stdout') or '').strip()}\n")
        if str(item.get("error") or "").strip():
            parts.append(f"- error: {str(item.get('error') or '').strip()}\n")
        parts.append("\n")

    return "".join(parts).strip()


__all__ = ["fallback_material_markdown", "fallback_search_markdown"]
