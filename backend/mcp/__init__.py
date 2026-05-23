"""MCP package forwarder.

Migration note (see ``docs/MIGRATION_PLAN.md``): the canonical location
for MCP implementation is now ``backend.integrations.mcp``. This package keeps
old submodule imports working while preserving ``python -m backend.mcp.stdio_server``
for external clients (Cherry Studio, mcp_config.json, scripts/start.py).

New code should import from ``backend.integrations.mcp.*`` directly.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "integrations" / "mcp"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]

__all__ = ["core", "search", "tools"]
