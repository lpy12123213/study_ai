"""MCP (Model Context Protocol) modules for AI tool integration.

Directory layout:
- `backend.mcp.core`: registry/server/client utilities
- `backend.mcp.search`: web search providers (Exa/BigModel/etc)
- `backend.mcp.tools`: stdio server + tool handlers + safe python compute
"""

from __future__ import annotations

__all__ = [
    "core",
    "search",
    "tools",
]
