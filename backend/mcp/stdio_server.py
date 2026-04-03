"""Legacy wrapper for MCP stdio server.

The implementation moved to `backend.mcp.tools.stdio_server` as part of the MCP regrouping
(`core/`, `search/`, `tools/`). We keep this module so existing docs/scripts still work:

    python -m backend.mcp.stdio_server
"""

from __future__ import annotations

import asyncio

from backend.mcp.tools.stdio_server import main


if __name__ == "__main__":
    asyncio.run(main())

