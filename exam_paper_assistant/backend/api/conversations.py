from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from backend.api.schemas import ConversationCreate
from database.models import create_conversation, delete_conversation, get_conversation, get_messages, list_conversations

router = APIRouter()


@router.get("/conversations")
async def get_conversations_list(limit: int = 50) -> List[dict]:
    """获取对话列表"""
    return await list_conversations(limit=limit)


@router.post("/conversations")
async def create_new_conversation(data: ConversationCreate) -> dict:
    """创建新对话"""
    conv_id = await create_conversation(title=data.title)
    return {"id": conv_id, "title": data.title}


@router.delete("/conversations/{conv_id}")
async def remove_conversation(conv_id: int) -> dict:
    """删除对话"""
    success = await delete_conversation(conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"success": True}


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: int) -> dict:
    """获取对话消息"""
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = await get_messages(conv_id)
    return {"conversation": conv, "messages": messages}
