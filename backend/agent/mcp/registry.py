from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.agent.mcp.protocol import MCPToolDefinition
from backend.agent.tools.utils.schema_validation import validate_and_coerce_args
from backend.agent.types import CompressedContext


@dataclass(frozen=True)
class MCPTool:
    definition: MCPToolDefinition
    execute: Callable[[Dict[str, Any], CompressedContext], Awaitable[Any]]


class MCPToolRegistry:
    """Dynamic tool registry with MCP-like list/call APIs.

    This is used to:
    - Provide a single source of truth for available tools (discovery).
    - Power Planner tool lists (no hard-coded dicts).
    - Support future tool-calling (tools/list + tools/call).
    """

    def __init__(self) -> None:
        self._tools: Dict[str, MCPTool] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        input_schema: Optional[Dict[str, Any]] = None,
        execute: Callable[[Dict[str, Any], CompressedContext], Awaitable[Any]],
    ) -> None:
        tool_name = str(name or "").strip()
        if not tool_name:
            raise ValueError("missing_tool_name")
        if tool_name in self._tools:
            raise ValueError(f"duplicate_tool_registration: {tool_name}")

        schema = dict(input_schema or {})
        if not schema:
            schema = {"type": "object", "additionalProperties": True}

        self._tools[tool_name] = MCPTool(
            definition=MCPToolDefinition(
                name=tool_name,
                description=str(description or "").strip() or tool_name,
                input_schema=schema,
            ),
            execute=execute,
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        return [tool.definition.to_dict() for tool in self._tools.values()]

    def get_tool(self, name: str) -> Optional[MCPToolDefinition]:
        tool_name = str(name or "").strip()
        tool = self._tools.get(tool_name)
        return tool.definition if tool else None

    async def call_tool(self, *, name: str, arguments: Optional[Dict[str, Any]], ctx: CompressedContext) -> Any:
        tool_name = str(name or "").strip()
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"tool_not_found: {tool_name}")
        args = validate_and_coerce_args(schema=tool.definition.input_schema, args=arguments or {}, tool_name=tool_name)
        return await tool.execute(args, ctx)
