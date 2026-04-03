from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class MCPToolDefinition:
    """A minimal MCP-style tool definition (JSON Schema input)."""

    name: str
    description: str
    input_schema: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": str(self.name or "").strip(),
            "description": str(self.description or "").strip(),
            "input_schema": dict(self.input_schema or {}),
        }

