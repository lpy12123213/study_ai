from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, func, select

from backend.database.engine import async_session_maker
from backend.database.schema import Conversation, Message


async def create_conversation(*, title: str = "新对话") -> int:
    async with async_session_maker() as session:
        conv = Conversation(title=str(title or "").strip() or "新对话")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return int(conv.id)


async def list_conversations(*, limit: int = 50) -> List[dict]:
    async with async_session_maker() as session:
        result = await session.execute(select(Conversation).order_by(Conversation.updated_at.desc()).limit(int(limit or 50)))
        convs = result.scalars().all()
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            }
            for c in convs
        ]


async def get_conversation(*, conv_id: int) -> Optional[dict]:
    async with async_session_maker() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == int(conv_id)))
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat() if conv.created_at else "",
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
        }


async def update_conversation_title(*, conv_id: int, title: str) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == int(conv_id)))
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        conv.title = str(title or "").strip() or "新对话"
        conv.updated_at = datetime.utcnow()
        await session.commit()
        return True


async def delete_conversation(*, conv_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == int(conv_id)))
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        await session.delete(conv)
        await session.commit()
        return True


async def delete_all_conversations() -> dict:
    """Delete all chat conversations and their messages.

    Notes:
    - Only clears `conversations` + `messages` tables; does not touch papers/canvas/etc.
    - Current DB schema does not scope conversations by user, so this clears everything.
    """

    async with async_session_maker() as session:
        conv_result = await session.execute(select(func.count(Conversation.id)))
        msg_result = await session.execute(select(func.count(Message.id)))
        conv_count = int(conv_result.scalar() or 0)
        msg_count = int(msg_result.scalar() or 0)

        await session.execute(delete(Message))
        await session.execute(delete(Conversation))
        await session.commit()
        return {"conversations": conv_count, "messages": msg_count}


async def add_message(
    *,
    conv_id: int,
    role: str,
    content: str,
    tool_calls: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> int:
    async with async_session_maker() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == int(conv_id)))
        conv = result.scalar_one_or_none()
        if conv:
            conv.updated_at = datetime.utcnow()

        msg = Message(
            conversation_id=int(conv_id),
            role=str(role or "").strip(),
            content=str(content or ""),
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return int(msg.id)


async def get_messages(*, conv_id: int) -> List[dict]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Message).where(Message.conversation_id == int(conv_id)).order_by(Message.created_at)
        )
        msgs = result.scalars().all()
        out: List[dict] = []
        for m in msgs:
            tool_calls = None
            if m.tool_calls:
                try:
                    tool_calls = json.loads(m.tool_calls)
                except Exception:
                    tool_calls = None
            out.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "tool_calls": tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
            )
        return out


async def fork_conversation(
    *,
    parent_conv_id: int,
    until_message_id: int,
    title: Optional[str] = None,
) -> dict:
    """Fork a conversation by copying messages up to `until_message_id` (inclusive)."""

    parent_conv_id = int(parent_conv_id or 0)
    until_message_id = int(until_message_id or 0)
    if parent_conv_id <= 0 or until_message_id <= 0:
        raise ValueError("invalid_parent_or_message_id")

    async with async_session_maker() as session:
        parent_result = await session.execute(select(Conversation).where(Conversation.id == parent_conv_id))
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise ValueError("conversation_not_found")

        msgs_result = await session.execute(
            select(Message).where(Message.conversation_id == parent_conv_id).order_by(Message.created_at)
        )
        msgs = list(msgs_result.scalars().all())
        if not msgs:
            raise ValueError("conversation_empty")

        copied: List[Message] = []
        copied_visible_count = 0
        found = False
        for m in msgs:
            copied.append(m)
            if m.role != "tool":
                copied_visible_count += 1
            if m.id == until_message_id:
                found = True
                break
        if not found:
            raise ValueError("message_not_found")

        new_title = str(title or "").strip() or f"{parent.title} - 分支"
        conv = Conversation(title=new_title)
        session.add(conv)
        await session.flush()

        for m in copied:
            session.add(
                Message(
                    conversation_id=int(conv.id),
                    role=m.role,
                    content=m.content,
                    tool_calls=m.tool_calls,
                    tool_call_id=m.tool_call_id,
                )
            )

        conv.updated_at = datetime.utcnow()
        await session.commit()

        return {
            "id": conv.id,
            "title": conv.title,
            "parent_conversation_id": parent_conv_id,
            "forked_from_message_id": until_message_id,
            "copied_message_count": len(copied),
            "copied_visible_message_count": copied_visible_count,
        }

