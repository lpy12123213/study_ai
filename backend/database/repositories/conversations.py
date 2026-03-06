from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, func, select

from backend.database.engine import async_session_maker
from backend.database.schema import Conversation, Message


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64]


async def create_conversation(*, user_id: str, title: str = "新对话") -> int:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        conv = Conversation(user_id=uid, title=str(title or "").strip() or "新对话")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return int(conv.id)


async def list_conversations(*, user_id: str, limit: int = 50) -> List[dict]:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == uid)
            .order_by(Conversation.updated_at.desc())
            .limit(int(limit or 50))
        )
        result = await session.execute(stmt)
        convs = result.scalars().all()
        return [
            {
                "id": c.id,
                "user_id": c.user_id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            }
            for c in convs
        ]


async def get_conversation(*, user_id: str, conv_id: int) -> Optional[dict]:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == int(conv_id),
                Conversation.user_id == uid,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        return {
            "id": conv.id,
            "user_id": conv.user_id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat() if conv.created_at else "",
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
        }


async def update_conversation_title(*, user_id: str, conv_id: int, title: str) -> bool:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == int(conv_id),
                Conversation.user_id == uid,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        conv.title = str(title or "").strip() or "新对话"
        conv.updated_at = datetime.utcnow()
        await session.commit()
        return True


async def delete_conversation(*, user_id: str, conv_id: int) -> bool:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == int(conv_id),
                Conversation.user_id == uid,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        await session.delete(conv)
        await session.commit()
        return True


async def delete_all_conversations(*, user_id: str) -> dict:
    """Delete all chat conversations and their messages.

    Notes:
    - Only clears `conversations` + `messages` for the given user.
    - Does not touch papers/canvas/etc.
    """

    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        conv_ids_result = await session.execute(select(Conversation.id).where(Conversation.user_id == uid))
        conv_ids = [int(x) for x in conv_ids_result.scalars().all()]
        if not conv_ids:
            return {"conversations": 0, "messages": 0}

        conv_count = len(conv_ids)
        msg_result = await session.execute(
            select(func.count(Message.id)).where(Message.conversation_id.in_(conv_ids))
        )
        msg_count = int(msg_result.scalar() or 0)

        await session.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        await session.execute(delete(Conversation).where(Conversation.user_id == uid))
        await session.commit()
        return {"conversations": conv_count, "messages": msg_count}


async def add_message(
    *,
    user_id: str,
    conv_id: int,
    role: str,
    content: str,
    tool_calls: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> int:
    uid = _normalize_user_id(user_id) or "1"
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == int(conv_id),
                Conversation.user_id == uid,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise ValueError("conversation_not_found")
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


async def get_messages(
    *,
    user_id: str,
    conv_id: int,
    limit: int = 200,
    before_id: Optional[int] = None,
    include_trace: bool = False,
    include_tool_content: bool = False,
    tool_content_max_chars: int = 2000,
) -> List[dict]:
    uid = _normalize_user_id(user_id) or "1"
    limit = max(1, min(int(limit or 200), 1000))
    tool_content_max_chars = max(0, min(int(tool_content_max_chars or 2000), 200_000))

    before_id_value: Optional[int] = None
    if before_id is not None:
        try:
            before_id_value = int(before_id)
        except Exception:
            before_id_value = None

    async with async_session_maker() as session:
        conv_result = await session.execute(
            select(Conversation.id).where(
                Conversation.id == int(conv_id),
                Conversation.user_id == uid,
            )
        )
        if conv_result.scalar_one_or_none() is None:
            return []

        stmt = select(Message).where(Message.conversation_id == int(conv_id))
        if before_id_value and before_id_value > 0:
            stmt = stmt.where(Message.id < int(before_id_value))
        if not include_trace:
            # Default view: user + final assistant messages only.
            stmt = stmt.where(Message.role != "tool")
            stmt = stmt.where(Message.tool_calls.is_(None))

        # Fetch latest N then reverse to chronological order for the frontend.
        stmt = stmt.order_by(Message.id.desc()).limit(limit)
        result = await session.execute(stmt)
        msgs = list(result.scalars().all())
        msgs.reverse()

        out: List[dict] = []
        for m in msgs:
            tool_calls = None
            if m.tool_calls:
                try:
                    tool_calls = json.loads(m.tool_calls)
                except Exception:
                    tool_calls = None

            content = m.content or ""
            tool_result_meta = None
            if m.role == "tool":
                tool_result_meta = {"size": len(content), "success": None, "error": None}
                try:
                    payload = json.loads(content) if content else None
                    if isinstance(payload, dict):
                        if isinstance(payload.get("success"), bool):
                            tool_result_meta["success"] = payload.get("success")
                        err = payload.get("error")
                        if isinstance(err, str) and err.strip():
                            tool_result_meta["error"] = err.strip()[:500]
                except Exception:
                    pass

                if not include_tool_content:
                    content = ""
                elif tool_content_max_chars > 0 and len(content) > tool_content_max_chars:
                    content = content[:tool_content_max_chars] + "...(truncated)"

            out.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "content": content,
                    "tool_calls": tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                    "tool_result_meta": tool_result_meta,
                }
            )
        return out


async def fork_conversation(
    *,
    user_id: str,
    parent_conv_id: int,
    until_message_id: int,
    title: Optional[str] = None,
) -> dict:
    """Fork a conversation by copying messages up to `until_message_id` (inclusive)."""

    uid = _normalize_user_id(user_id) or "1"
    parent_conv_id = int(parent_conv_id or 0)
    until_message_id = int(until_message_id or 0)
    if parent_conv_id <= 0 or until_message_id <= 0:
        raise ValueError("invalid_parent_or_message_id")

    async with async_session_maker() as session:
        parent_result = await session.execute(
            select(Conversation).where(
                Conversation.id == parent_conv_id,
                Conversation.user_id == uid,
            )
        )
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
        conv = Conversation(user_id=uid, title=new_title)
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
