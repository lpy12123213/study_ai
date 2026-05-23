from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

ChatToolHandler = Callable[..., Awaitable[Dict[str, Any]]]


def _tool_name(spec: Dict[str, Any]) -> str:
    fn = spec.get("function") if isinstance(spec.get("function"), dict) else {}
    return str(fn.get("name") or "").strip()


def _tool_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    fn = spec.get("function") if isinstance(spec.get("function"), dict) else {}
    params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
    return dict(params)


@dataclass(frozen=True)
class ChatTool:
    name: str
    spec: Dict[str, Any]
    schema: Dict[str, Any]
    handler: Optional[ChatToolHandler] = None


class ChatToolRegistry:
    def __init__(self, specs: Iterable[Dict[str, Any]] = ()) -> None:
        self._tools: Dict[str, ChatTool] = {}
        for spec in specs:
            name = _tool_name(spec)
            if name:
                self._tools[name] = ChatTool(name=name, spec=dict(spec), schema=_tool_schema(spec))

    def register_handler(self, name: str, handler: ChatToolHandler) -> None:
        tool_name = str(name or "").strip()
        if not tool_name:
            raise ValueError("missing_chat_tool_name")
        existing = self._tools.get(tool_name)
        if existing is None:
            self._tools[tool_name] = ChatTool(name=tool_name, spec={}, schema={}, handler=handler)
            return
        self._tools[tool_name] = ChatTool(
            name=existing.name,
            spec=existing.spec,
            schema=existing.schema,
            handler=handler,
        )

    def get(self, name: str) -> Optional[ChatTool]:
        return self._tools.get(str(name or "").strip())

    def schema_for(self, name: str) -> Optional[Dict[str, Any]]:
        tool = self.get(name)
        if tool is None:
            return None
        return dict(tool.schema)

    def specs(self, names: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        if names is None:
            return [dict(tool.spec) for tool in self._tools.values() if tool.spec]
        allowed = {str(name or "").strip() for name in names if str(name or "").strip()}
        return [dict(tool.spec) for name, tool in self._tools.items() if name in allowed and tool.spec]

    def names(self) -> List[str]:
        return list(self._tools.keys())
