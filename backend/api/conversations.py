from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.api.schemas import ConversationCreate, ConversationForkRequest, ConversationUpdate
from backend.database.models import (
    create_conversation,
    delete_conversation,
    fork_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)

router = APIRouter(dependencies=[Depends(require_auth)])


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


@router.post("/conversations/{conv_id}/fork")
async def fork_existing_conversation(conv_id: int, data: ConversationForkRequest) -> dict:
    """
    从某条消息开始“分叉”对话，生成一个新的对话（复制父对话的消息前缀）。

    说明：
    - 用于前端画布式分叉对话：分叉后的新对话可以继续独立对话。
    - 复制的消息为父对话中按时间排序，直到 `message_id`（包含该条消息）。
    """
    try:
        return await fork_conversation(
            parent_conv_id=conv_id,
            until_message_id=data.message_id,
            title=data.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: int, data: ConversationUpdate) -> dict:
    """更新对话信息（目前仅支持标题）"""
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title_required")

    success = await update_conversation_title(conv_id, title)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")

    conv = await get_conversation(conv_id)
    return {"success": True, "conversation": conv}
