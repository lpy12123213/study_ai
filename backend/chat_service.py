"""Compatibility wrapper for the chat service.

The original implementation lived in a single huge file (`backend/chat_service.py`).
It has been split into `backend/chat/*` modules for maintainability.
"""

from __future__ import annotations

from backend.chat.prompts import PLAN_TAG_CLOSE, PLAN_TAG_OPEN, get_system_prompt
from backend.chat.service import ChatService, chat_service
from backend.chat.tools_spec import TOOLS

__all__ = [
    "ChatService",
    "chat_service",
    "TOOLS",
    "PLAN_TAG_OPEN",
    "PLAN_TAG_CLOSE",
    "get_system_prompt",
]

