"""Interactive AI question-generation CLI.

Historically this lived in a single ``backend/cli/question_generate.py`` module;
it has been split into focused submodules (``args``, ``prompts``, ``mcp_tools``,
``session``, ``runner``, ``render``, ``review``, ``app``) for maintainability.

The public surface is unchanged: ``python -m backend.cli.question_generate`` and
``from backend.cli.question_generate import main`` keep working. ``RunParams`` and
the handful of helpers that other code (and tests) reference are re-exported here
so existing imports continue to resolve.
"""

from __future__ import annotations

from . import helpers, mcp_tools
from .app import main
from .args import RunParams
from .helpers import _resolve_cli_mcp_search_model
from .mcp_tools import _ai_search_materials_via_mcp, _exec_mcp_web_search_tool

__all__ = [
    "RunParams",
    "_ai_search_materials_via_mcp",
    "_exec_mcp_web_search_tool",
    "_resolve_cli_mcp_search_model",
    "helpers",
    "main",
    "mcp_tools",
]
