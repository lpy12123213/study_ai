from __future__ import annotations

import json
import logging
import os
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import ChatRequest
from backend.chat_service import chat_service
from backend.database.models import add_message, get_conversation, get_messages, update_conversation_title

router = APIRouter(dependencies=[Depends(require_auth)])

logger = logging.getLogger(__name__)


def _truncate_display_width(text: str, max_width: int) -> str:
    s = str(text or "").strip()
    if not s or max_width <= 0:
        return ""
    width = 0
    out = []
    for ch in s:
        ch_w = 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        if width + ch_w > max_width:
            break
        out.append(ch)
        width += ch_w
    clipped = "".join(out).strip()
    if clipped and len(clipped) < len(s):
        return clipped + "..."
    return clipped or s[: max(0, max_width)]


@router.post("/chat")
async def chat_endpoint(request: ChatRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
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
    except Exception:
        max_context_messages = 40
    max_context_messages = max(0, min(max_context_messages, 200))

    history_limit = max_context_messages or 40
    history = await get_messages(user_id=user_id, conv_id=conv_id, limit=history_limit)

    try:
        await add_message(user_id=user_id, conv_id=conv_id, role="user", content=user_message)
    except Exception:
        logger.exception("Failed to persist user message")

    async def generate():
        async for chunk in chat_service.chat(
            history,
            user_message,
            user_id=user_id,
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
                            user_id=user_id,
                            conv_id=conv_id,
                            role="assistant",
                            content=chunk.get("content", "") or "",
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
                            user_id=user_id,
                            conv_id=conv_id,
                            role="tool",
                            content=json.dumps(chunk.get("result"), ensure_ascii=False),
                            tool_call_id=chunk.get("tool_call_id", ""),
                        )
                    except Exception:
                        logger.exception("Failed to persist tool_result message")
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if chunk_type == "assistant_final":
                final_content = chunk.get("content", "")
                try:
                    await add_message(user_id=user_id, conv_id=conv_id, role="assistant", content=final_content)
                except Exception:
                    logger.exception("Failed to persist assistant final message")

                if len(history) == 0:
                    title = _truncate_display_width(user_message, 30)
                    try:
                        await update_conversation_title(user_id=user_id, conv_id=conv_id, title=title)
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
