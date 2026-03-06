"""Legacy compatibility shim for the old MCP entrypoint.

Prefer `python -m backend.mcp.stdio_server`.
"""

from __future__ import annotations

import asyncio

from backend.mcp.stdio_server import ExamPaperMCPServer, main

__all__ = ["ExamPaperMCPServer", "main"]


if __name__ == "__main__":
    asyncio.run(main())
