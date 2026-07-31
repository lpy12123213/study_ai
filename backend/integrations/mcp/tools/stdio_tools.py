"""MCP stdio tool definitions (Tool list).

Domain slices live in ``stdio_tool_groups.py``; this module keeps the original
``get_stdio_tools()`` entrypoint and ordering.
"""

from __future__ import annotations

from typing import List

from backend.integrations.mcp.tools.stdio_tool_groups import (
    agent_knowledge_tools,
    diagram_tools,
    paper_analysis_tools,
    paper_compose_tools,
    question_bank_tools,
    search_and_compute_tools,
)
from mcp.types import Tool


def get_stdio_tools() -> List[Tool]:
    return [
        *question_bank_tools(),
        *paper_compose_tools(),
        *agent_knowledge_tools(),
        *search_and_compute_tools(),
        *paper_analysis_tools(),
        *diagram_tools(),
    ]
