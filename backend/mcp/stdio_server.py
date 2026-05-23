"""External entrypoint wrapper for ``python -m backend.mcp.stdio_server``.

The implementation lives at ``backend.integrations.mcp.tools.stdio_server``.
We keep this thin wrapper so external scripts and ``mcp_config.json``
configurations do not need to change.
"""

from __future__ import annotations

import asyncio

from backend.integrations.mcp.tools.stdio_server import main

__all__ = ["main"]

if __name__ == "__main__":
    asyncio.run(main())
