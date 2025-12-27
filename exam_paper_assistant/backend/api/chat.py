from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.schemas import ChatRequest
from backend.chat_service import chat_service
from database.models import add_message, get_conversation, get_messages, update_conversation_title

router = APIRouter()


@router.post("/chat")
async def chat_endpoint(request: ChatRequest) -> StreamingResponse:
    """
    处理聊天请求，返回 SSE 流式响应（前端通过 fetch 读取）。
    支持学科选择。
    """
    conv_id = request.conversation_id
    user_message = request.message
    subject = request.subject

    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    await add_message(conv_id, "user", user_message)

    history = await get_messages(conv_id)
    history = history[:-1]

    async def generate():
        collected_content = ""
        collected_tool_calls = []
        tool_results = []

        async for chunk in chat_service.chat(history, user_message, subject=subject):
            chunk_type = chunk.get("type")

            if chunk_type == "assistant":
                collected_content = chunk.get("content", "")
                if chunk.get("tool_calls"):
                    collected_tool_calls = chunk["tool_calls"]
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if chunk_type in {"tool_start", "tool_result", "stream_start", "text_delta", "iteration", "error"}:
                if chunk_type == "tool_result":
                    tool_results.append(chunk)
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if chunk_type == "assistant_final":
                if collected_tool_calls:
                    await add_message(
                        conv_id,
                        "assistant",
                        collected_content,
                        tool_calls=json.dumps(collected_tool_calls, ensure_ascii=False),
                    )
                    for tr in tool_results:
                        await add_message(
                            conv_id,
                            "tool",
                            json.dumps(tr["result"], ensure_ascii=False),
                            tool_call_id=tr["tool_call_id"],
                        )

                final_content = chunk.get("content", "")
                await add_message(conv_id, "assistant", final_content)

                if len(history) == 0:
                    title = user_message[:30] + ("..." if len(user_message) > 30 else "")
                    await update_conversation_title(conv_id, title)

                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

