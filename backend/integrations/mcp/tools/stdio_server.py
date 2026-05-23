"""MCP stdio server entrypoint.

This file is intentionally kept small. Tool definitions and handlers live in:
- `backend/mcp/stdio_tools.py`
- `backend/mcp/stdio_handlers.py`

Run:
- `python -m backend.mcp.stdio_server`
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, List, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

if __package__ is None or __package__ == "":
    # Allow running as a script.
    # NOTE: this file lives under `backend/mcp/tools/`, so repo root is 3 levels up.
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from backend.core.settings import DEFAULT_SUBJECT
from backend.integrations.mcp.tools.stdio_handlers import handle_tool_call
from backend.integrations.mcp.tools.stdio_tools import get_stdio_tools


class ExamPaperMCPServer:
    def __init__(self) -> None:
        self.server = Server("exam-paper-assistant")
        self.current_subject = DEFAULT_SUBJECT
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return get_stdio_tools()

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
            return await handle_tool_call(self, name, arguments)

    async def run(self) -> None:
        """Start MCP stdio server."""
        async with stdio_server() as (read_stream, write_stream):
            # MCP stdio protocol requires stdout to be *only* JSON-RPC messages.
            original_stdout = sys.stdout
            try:
                sys.stdout = sys.stderr
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )
            finally:
                sys.stdout = original_stdout


async def main() -> None:
    server = ExamPaperMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
