from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.api.schemas import ConversationCreate, ConversationForkRequest, ConversationUpdate
from backend.database.repositories.content.conversations import (
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
async def get_conversations_list(limit: int = 50, user: dict = Depends(require_auth)) -> List[dict]:
    """获取对话列表"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await list_conversations(user_id=user_id, limit=limit)


@router.post("/conversations")
async def create_new_conversation(data: ConversationCreate, user: dict = Depends(require_auth)) -> dict:
    """创建新对话"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    conv_id = await create_conversation(user_id=user_id, title=data.title)
    return {"id": conv_id, "title": data.title}


@router.delete("/conversations/{conv_id}")
async def remove_conversation(conv_id: int, user: dict = Depends(require_auth)) -> dict:
    """删除对话"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    success = await delete_conversation(user_id=user_id, conv_id=conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"success": True}


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(
    conv_id: int,
    user: dict = Depends(require_auth),
    limit: int = Query(100, ge=1, le=100),
    before_id: int = Query(0, ge=0),
    include_trace: bool = Query(False),
    include_tool_content: bool = Query(False),
) -> dict:
    """获取对话消息"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    conv = await get_conversation(user_id=user_id, conv_id=conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = await get_messages(
        user_id=user_id,
        conv_id=conv_id,
        limit=limit,
        before_id=(before_id or None) if before_id else None,
        include_trace=include_trace,
        include_tool_content=include_tool_content,
    )

    next_before_id = int(messages[0]["id"]) if messages else (before_id or 0)
    return {
        "conversation": conv,
        "messages": messages,
        "paging": {
            "limit": limit,
            "before_id": before_id or 0,
            "next_before_id": next_before_id,
            "include_trace": include_trace,
            "include_tool_content": include_tool_content,
        },
    }


@router.post("/conversations/{conv_id}/fork")
async def fork_existing_conversation(
    conv_id: int, data: ConversationForkRequest, user: dict = Depends(require_auth)
) -> dict:
    """
    从某条消息开始“分叉”对话，生成一个新的对话（复制父对话的消息前缀）。

    说明：
    - 用于前端画布式分叉对话：分叉后的新对话可以继续独立对话。
    - 复制的消息为父对话中按时间排序，直到 `message_id`（包含该条消息）。
    """
    try:
        user_id = str((user or {}).get("user_id") or "").strip()
        if not user_id:
            raise HTTPException(status_code=401, detail="invalid_or_expired_token")
        return await fork_conversation(
            user_id=user_id,
            parent_conv_id=conv_id,
            until_message_id=data.message_id,
            title=data.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: int, data: ConversationUpdate, user: dict = Depends(require_auth)) -> dict:
    """更新对话信息（目前仅支持标题）"""
    title = (data.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title_required")

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    success = await update_conversation_title(user_id=user_id, conv_id=conv_id, title=title)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")

    conv = await get_conversation(user_id=user_id, conv_id=conv_id)
    return {"success": True, "conversation": conv}
