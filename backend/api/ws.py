"""WebSocket streaming endpoints for long-running tasks.

Provides a persistent bidirectional connection that avoids SSE timeout issues
with proxies and firewalls. Supports the same `after_seq` resumability pattern.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.api.auth import validate_ws_token
from backend.core.logging_utils import get_logger
from backend.database.repositories.system.tasks import (
    get_task as db_get_task,
    list_task_events as db_list_task_events,
)
from backend.shared.tasks import task_runtime

router = APIRouter(tags=["websocket"])
logger = get_logger(__name__)


async def _send_event(websocket: WebSocket, event: dict) -> bool:
    """Send a JSON event. Returns False if the connection is dead."""
    try:
        await websocket.send_json(event)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except Exception:
        logger.exception("ws_send_event_failed")
        return False


async def _stream_task_events(
    websocket: WebSocket,
    *,
    task_id: str,
    user_id: str,
    after_seq: int,
) -> None:
    """Stream events for a task, prefer DB-backed replay (durable) and fall back to
    in-memory runtime stream when the task isn't persisted yet.

    This mirrors the SSE endpoint logic so refresh + resume works the same way.
    """

    last_sent = max(0, int(after_seq or 0))
    last_ping_at = 0.0
    heartbeat_s = 10.0

    while True:
        # Allow client to send messages in parallel (e.g. cancel). We use a
        # non-blocking receive to detect disconnects quickly.
        if websocket.client_state != WebSocketState.CONNECTED:
            return

        task = await db_get_task(user_id=user_id, task_id=task_id, include_events=False)
        if not task:
            # No DB row yet — fall back to in-memory runtime stream.
            runtime_task = await task_runtime.get_task(task_id)
            if runtime_task and str(runtime_task.user_id or "") == user_id:
                async for event in task_runtime.stream(task_id, after_seq=last_sent, heartbeat_s=heartbeat_s):
                    if not await _send_event(websocket, event):
                        return
                return
            await _send_event(
                websocket,
                {
                    "taskId": task_id,
                    "seq": last_sent,
                    "type": "error",
                    "data": {"error": "task_not_found"},
                },
            )
            return

        events = await db_list_task_events(user_id=user_id, task_id=task_id, after_seq=last_sent, limit=500)
        for evt in events:
            seq = int(evt.get("seq") or 0)
            if seq <= last_sent:
                continue
            last_sent = seq
            if not await _send_event(websocket, evt):
                return

        # Drain page-after-page if we filled the limit (lots of buffered events).
        if len(events) >= 500:
            continue

        # Terminal: stop streaming.
        if str(task.get("status") or "") != "running":
            return

        now = time.time()
        if now - last_ping_at >= heartbeat_s:
            last_ping_at = now
            if not await _send_event(
                websocket,
                {
                    "taskId": task_id,
                    "seq": last_sent,
                    "type": "ping",
                    "data": {"status": "running", "last_seq": last_sent},
                },
            ):
                return

        await asyncio.sleep(0.5)


@router.websocket("/ws/tasks/{task_id}")
async def ws_task_stream(
    websocket: WebSocket,
    task_id: str,
    after_seq: int = Query(0, ge=0),
    token: str = Query(""),
):
    """WebSocket endpoint for streaming task events.

    Connection protocol:
    1. Client connects with `?token=<jwt>&after_seq=<n>`
    2. Server validates token, accepts connection
    3. Server streams events as JSON messages (durable: from DB events table)
    4. Server sends `{type: "ping"}` every ~10s as a heartbeat
    5. Server closes connection when task completes/fails/is-cancelled
    """

    user = validate_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="unauthorized")
        return

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        await websocket.close(code=4001, reason="unauthorized")
        return

    await websocket.accept()

    # Start a background task to drain incoming client messages (ping/cancel)
    # so the connection stays responsive and we detect disconnects fast.
    receive_task: asyncio.Task | None = None

    async def _drain_client_messages() -> None:
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    try:
                        await websocket.send_json({"type": "pong"})
                    except Exception:
                        return
        except WebSocketDisconnect:
            return
        except Exception:
            return

    try:
        receive_task = asyncio.create_task(_drain_client_messages())
        await _stream_task_events(websocket, task_id=task_id, user_id=user_id, after_seq=after_seq)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("ws_task_stream_error", extra={"task_id": task_id, "user_id": user_id})
        try:
            await websocket.send_json({"type": "error", "data": {"error": "internal_error"}})
        except Exception:
            pass
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/chat")
async def ws_chat_stream(
    websocket: WebSocket,
    token: str = Query(""),
):
    """WebSocket endpoint for chat streaming.

    Protocol:
    1. Client connects with `?token=<jwt>`
    2. Client sends: `{"type": "message", "conversation_id": 123, "content": "..."}`
    3. Server streams back events (same format as SSE chat endpoint)
    4. Server sends `{"type": "done"}` when complete
    """

    user = validate_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="unauthorized")
        return

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        await websocket.close(code=4001, reason="unauthorized")
        return

    await websocket.accept()

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                return

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                await websocket.send_json({"type": "error", "data": {"error": "invalid_json"}})
                continue

            msg_type = str(msg.get("type") or "").strip()

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "message":
                conversation_id = msg.get("conversation_id")
                content = str(msg.get("content") or "").strip()

                if not conversation_id or not content:
                    await websocket.send_json({"type": "error", "data": {"error": "missing_fields"}})
                    continue

                from backend.workspace.chat.service import get_chat_service
                from backend.database.repositories.content.conversations import (
                    get_conversation, get_messages, add_message, update_conversation_title
                )
                import json as _json

                service = get_chat_service()
                conv_id = int(conversation_id)

                conv = await get_conversation(user_id=user_id, conv_id=conv_id)
                if not conv:
                    await websocket.send_json({"type": "error", "data": {"error": "conversation_not_found"}})
                    continue

                history = await get_messages(user_id=user_id, conv_id=conv_id, limit=40)

                try:
                    await add_message(user_id=user_id, conv_id=conv_id, role="user", content=content)
                except Exception:
                    logger.exception("ws_chat_persist_user_message_failed")

                subject = str(msg.get("subject") or "").strip() or None
                model = str(msg.get("model") or "").strip() or None
                sub_model = str(msg.get("sub_model") or "").strip() or None

                try:
                    async for chunk in service.chat(
                        history,
                        content,
                        user_id=user_id,
                        subject=subject,
                        model=model,
                        sub_model=sub_model,
                    ):
                        chunk_type = chunk.get("type")

                        if chunk_type == "assistant":
                            tool_calls = chunk.get("tool_calls") or []
                            if tool_calls:
                                try:
                                    await add_message(
                                        user_id=user_id,
                                        conv_id=conv_id,
                                        role="assistant",
                                        content=chunk.get("content", "") or "",
                                        tool_calls=_json.dumps(tool_calls, ensure_ascii=False),
                                    )
                                except Exception:
                                    logger.exception("ws_chat_persist_tool_calls_failed")

                        elif chunk_type == "tool_result":
                            try:
                                await add_message(
                                    user_id=user_id,
                                    conv_id=conv_id,
                                    role="tool",
                                    content=_json.dumps(chunk.get("result"), ensure_ascii=False),
                                    tool_call_id=chunk.get("tool_call_id", ""),
                                )
                            except Exception:
                                logger.exception("ws_chat_persist_tool_result_failed")

                        elif chunk_type == "assistant_final":
                            final_content = chunk.get("content", "")
                            try:
                                await add_message(user_id=user_id, conv_id=conv_id, role="assistant", content=final_content)
                            except Exception:
                                logger.exception("ws_chat_persist_final_failed")

                            if len(history) == 0:
                                title = content[:30]
                                try:
                                    await update_conversation_title(user_id=user_id, conv_id=conv_id, title=title)
                                except Exception:
                                    pass

                        try:
                            await websocket.send_json(chunk)
                        except (WebSocketDisconnect, RuntimeError):
                            return

                    await websocket.send_json({"type": "done"})
                except Exception as exc:
                    logger.exception("ws_chat_error", extra={"user_id": user_id})
                    try:
                        await websocket.send_json({"type": "error", "data": {"error": str(exc)}})
                    except Exception:
                        pass
                continue

            await websocket.send_json({"type": "error", "data": {"error": f"unknown_type: {msg_type}"}})

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("ws_chat_unexpected_error", extra={"user_id": user_id})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
