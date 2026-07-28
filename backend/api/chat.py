from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import ChatRequest
from backend.api.sse_utils import is_sse_client_disconnected
from backend.core.logging_utils import get_logger
from backend.database.repositories.content.conversations import (
    add_message,
    get_conversation,
    get_messages,
)
from backend.workspace.chat.cancel_registry import get_chat_cancel_registry
from backend.workspace.chat.service import ChatService, get_chat_service
from backend.workspace.chat.titles import update_title_for_first_user_message

router = APIRouter(dependencies=[Depends(require_auth)])

logger = get_logger(__name__)


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    http_request: Request,
    user: dict = Depends(require_auth),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    """
    处理聊天请求，返回 SSE 流式响应（前端通过 fetch 读取）。
    支持学科选择。
    """
    conv_id = request.conversation_id
    user_message = request.message
    subject = request.subject
    model_override = (request.model or "").strip() or None
    sub_model_override = (request.sub_model or "").strip() or None

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    conv = await get_conversation(user_id=user_id, conv_id=conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    try:
        max_context_messages = int(os.getenv("CHAT_CONTEXT_MAX_MESSAGES") or "40")
    except ValueError:
        max_context_messages = 40
    max_context_messages = max(0, min(max_context_messages, 200))

    history_limit = max_context_messages or 40
    history = await get_messages(user_id=user_id, conv_id=conv_id, limit=history_limit)

    try:
        await add_message(user_id=user_id, conv_id=conv_id, role="user", content=user_message)
        try:
            await update_title_for_first_user_message(
                user_id=user_id,
                conv_id=conv_id,
                user_message=user_message,
                history_count=len(history),
            )
        except Exception:
            logger.exception("Failed to update conversation title")
    except Exception:
        logger.exception("Failed to persist user message")

    async def generate():
        registry = get_chat_cancel_registry()
        cancel_event = registry.register(user_id, conv_id)
        try:
            async for chunk in service.chat(
                history,
                user_message,
                user_id=user_id,
                subject=subject,
                model=model_override,
                sub_model=sub_model_override,
                intent=(request.intent or "").strip() or None,
                cancel_event=cancel_event,
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "assistant":
                    # Persist each tool-call round as an assistant message so the frontend can render tool nodes later.
                    tool_calls = chunk.get("tool_calls") or []
                    if tool_calls:
                        try:
                            await add_message(
                                user_id=user_id,
                                conv_id=conv_id,
                                role="assistant",
                                content=chunk.get("content", "") or "",
                                tool_calls=json.dumps(tool_calls, ensure_ascii=False),
                            )
                        except Exception:
                            logger.exception("Failed to persist assistant tool_calls message")
                    if await is_sse_client_disconnected(http_request):
                        return
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                if chunk_type in {
                    "tool_start",
                    "tool_result",
                    "stream_start",
                    "text_delta",
                    "thinking_delta",
                    "iteration",
                    "error",
                }:
                    if chunk_type == "tool_result":
                        # Persist tool results as tool-role messages (indexed by tool_call_id).
                        try:
                            await add_message(
                                user_id=user_id,
                                conv_id=conv_id,
                                role="tool",
                                content=json.dumps(chunk.get("result"), ensure_ascii=False),
                                tool_call_id=chunk.get("tool_call_id", ""),
                            )
                        except Exception:
                            logger.exception("Failed to persist tool_result message")
                    if await is_sse_client_disconnected(http_request):
                        return
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                if chunk_type == "cancelled":
                    # 服务端取消确认（视觉规划 §9.2）：落一条说明性 assistant 消息，
                    # 保证刷新后历史里这轮以明确的停止状态收尾。
                    try:
                        await add_message(
                            user_id=user_id,
                            conv_id=conv_id,
                            role="assistant",
                            content=chunk.get("content", "") or "（已按用户要求停止生成。）",
                        )
                    except Exception:
                        logger.exception("Failed to persist cancelled note")
                    if await is_sse_client_disconnected(http_request):
                        return
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

                if chunk_type == "assistant_final":
                    final_content = chunk.get("content", "")
                    try:
                        await add_message(user_id=user_id, conv_id=conv_id, role="assistant", content=final_content)
                    except Exception:
                        logger.exception("Failed to persist assistant final message")

                    if await is_sse_client_disconnected(http_request):
                        return
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue

            if await is_sse_client_disconnected(http_request):
                return
            yield "data: [DONE]\n\n"
        finally:
            registry.release(user_id, conv_id, cancel_event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/chat/{conversation_id}/cancel")
async def cancel_chat(
    conversation_id: int,
    user: dict = Depends(require_auth),
) -> dict:
    """请求取消该会话当前进行中的生成。

    返回 accepted=True 表示已向活动运行发出取消信号；实际停止由流内的
    `cancelled` 事件确认（协作式：正在执行的写类工具会先完整结束）。
    没有活动运行时返回 accepted=False（幂等，不视为错误）。
    """
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    accepted = get_chat_cancel_registry().cancel(user_id, conversation_id)
    return {"success": True, "accepted": accepted}
