from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import ChatRequest
from backend.chat_service import chat_service
from backend.database.models import add_message, get_conversation, get_messages, update_conversation_title

router = APIRouter(dependencies=[Depends(require_auth)])

logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat_endpoint(request: ChatRequest) -> StreamingResponse:
    """
    处理聊天请求，返回 SSE 流式响应（前端通过 fetch 读取）。
    支持学科选择。
    """
    conv_id = request.conversation_id
    user_message = request.message
    subject = request.subject
    model_override = (request.model or "").strip() or None
    sub_model_override = (request.sub_model or "").strip() or None

    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    history = await get_messages(conv_id)

    try:
        await add_message(conv_id, "user", user_message)
    except Exception:
        logger.exception("Failed to persist user message")

    async def generate():
        async for chunk in chat_service.chat(
            history,
            user_message,
            subject=subject,
            model=model_override,
            sub_model=sub_model_override,
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "assistant":
                # Persist each tool-call round as an assistant message so the frontend can render tool nodes later.
                tool_calls = chunk.get("tool_calls") or []
                if tool_calls:
                    try:
                        await add_message(
                            conv_id,
                            "assistant",
                            chunk.get("content", "") or "",
                            tool_calls=json.dumps(tool_calls, ensure_ascii=False),
                        )
                    except Exception:
                        logger.exception("Failed to persist assistant tool_calls message")
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if chunk_type in {"tool_start", "tool_result", "stream_start", "text_delta", "iteration", "error"}:
                if chunk_type == "tool_result":
                    # Persist tool results as tool-role messages (indexed by tool_call_id).
                    try:
                        await add_message(
                            conv_id,
                            "tool",
                            json.dumps(chunk.get("result"), ensure_ascii=False),
                            tool_call_id=chunk.get("tool_call_id", ""),
                        )
                    except Exception:
                        logger.exception("Failed to persist tool_result message")
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if chunk_type == "assistant_final":
                final_content = chunk.get("content", "")
                try:
                    await add_message(conv_id, "assistant", final_content)
                except Exception:
                    logger.exception("Failed to persist assistant final message")

                if len(history) == 0:
                    title = user_message[:30] + ("..." if len(user_message) > 30 else "")
                    try:
                        await update_conversation_title(conv_id, title)
                    except Exception:
                        logger.exception("Failed to update conversation title")

                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
