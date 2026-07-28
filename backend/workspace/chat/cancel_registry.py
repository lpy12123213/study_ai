"""Chat 取消注册表：为进行中的对话流提供可验证的服务端取消契约。

- 以 (user_id, conversation_id) 为键，一个会话同一时刻只跟踪最新一次运行；
- cancel() 只是置位 asyncio.Event，由 ChatService.chat 在安全边界协作式停止；
- release() 按事件身份释放，避免旧运行结束时误删新运行的注册。
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple

_Key = Tuple[str, int]


class ChatCancelRegistry:
    def __init__(self) -> None:
        self._events: Dict[_Key, asyncio.Event] = {}

    def register(self, user_id: str, conversation_id: int) -> asyncio.Event:
        event = asyncio.Event()
        self._events[(str(user_id), int(conversation_id))] = event
        return event

    def cancel(self, user_id: str, conversation_id: int) -> bool:
        event = self._events.get((str(user_id), int(conversation_id)))
        if event is None:
            return False
        event.set()
        return True

    def release(self, user_id: str, conversation_id: int, event: asyncio.Event) -> None:
        key = (str(user_id), int(conversation_id))
        if self._events.get(key) is event:
            self._events.pop(key, None)

    def active(self, user_id: str, conversation_id: int) -> bool:
        return (str(user_id), int(conversation_id)) in self._events


_registry: Optional[ChatCancelRegistry] = None


def get_chat_cancel_registry() -> ChatCancelRegistry:
    global _registry
    if _registry is None:
        _registry = ChatCancelRegistry()
    return _registry
