from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.workspace.chat.llm_mixin import ChatLLMMixin
from backend.workspace.chat.tools_mixin import ChatToolsMixin
from backend.core.logging_utils import get_logger
from backend.core.settings import MAIN_MODEL, MAX_TOOL_ITERATIONS

MUTUALLY_EXCLUSIVE_CHAT_TOOLS = {"create_paper"}
logger = get_logger(__name__)


class ChatService(ChatLLMMixin, ChatToolsMixin):
    def __init__(self) -> None:
        self.crawler = None
        self.current_subject = "高中数学"
        self.question_cache = {}

    def _generate_fallback_response(self, tool_results: List[Dict[str, Any]]) -> str:
        if not tool_results:
            return "操作已完成。"

        responses: List[str] = []
        for tr in tool_results:
            try:
                result = json.loads(tr.get("content", "{}"))
                if not isinstance(result, dict):
                    continue

                if "questions" in result:
                    questions = result.get("questions", []) if isinstance(result.get("questions"), list) else []
                    total = int(result.get("total") or len(questions))
                    if questions:
                        responses.append(f"搜索到 {total} 道题目，已展示 {len(questions)} 道。")
                    else:
                        responses.append("未找到符合条件的题目，请尝试其他关键词。")
                    continue

                if "paper_id" in result:
                    paper_id = result.get("paper_id")
                    responses.append(f"试卷创建成功！试卷ID: {paper_id}")
                    continue

                if "papers" in result:
                    count = int(result.get("count") or 0)
                    responses.append(f"找到 {count} 份已保存的试卷。")
                    continue

                if result.get("success") is False:
                    err = str(result.get("error") or "未知错误")
                    responses.append(f"操作失败: {err}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        if responses:
            return "\n\n".join(responses) + "\n\n请查看上方的详细结果。如需继续操作，请告诉我。"
        return "操作已完成，请查看上方的工具执行结果。"

    def _prepare_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        fn = tool_call.get("function") if isinstance(tool_call, dict) else {}
        tool_name = str((fn or {}).get("name") or "").strip()
        tool_id = str(tool_call.get("id") or "").strip()
        raw_args = (fn or {}).get("arguments") if isinstance(fn, dict) else {}
        if isinstance(raw_args, str):
            try:
                tool_args = json.loads(raw_args)
            except (TypeError, ValueError, json.JSONDecodeError):
                tool_args = {}
        else:
            tool_args = raw_args if isinstance(raw_args, dict) else {}
        return {
            "tool_call": tool_call,
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments": self._coerce_tool_args(tool_name, tool_args),
        }

    def _can_execute_tool_calls_concurrently(self, prepared: List[Dict[str, Any]]) -> bool:
        if len(prepared) <= 1:
            return False
        names = [str(x.get("tool_name") or "").strip() for x in prepared]
        if any(not name for name in names):
            return False
        if any(name in MUTUALLY_EXCLUSIVE_CHAT_TOOLS for name in names):
            return False
        return True

    async def _execute_prepared_tool_call(
        self,
        prepared: Dict[str, Any],
        *,
        sub_model: Optional[str],
        user_id: str,
    ) -> Dict[str, Any]:
        tool_name = str(prepared.get("tool_name") or "").strip()
        tool_args = prepared.get("arguments") if isinstance(prepared.get("arguments"), dict) else {}
        try:
            result = await self.execute_tool(
                tool_name,
                tool_args,
                sub_model=sub_model,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("chat_tool_call_failed", extra={"tool_name": tool_name}, exc_info=True)
            result = {"success": False, "error": str(exc or "tool_failed")}
        return {
            "tool_call_id": str(prepared.get("tool_call_id") or "").strip(),
            "tool_name": tool_name,
            "result": result,
        }

    async def chat(
        self,
        history: List[Dict[str, Any]],
        user_message: str,
        subject: str = "高中数学",
        *,
        user_id: str,
        model: Optional[str] = None,
        sub_model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        self.current_subject = subject
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("missing_user_id")

        main_model = (model or MAIN_MODEL).strip() or MAIN_MODEL
        sub_model_effective = (sub_model or "").strip() or None

        messages = self._build_messages(history, user_message, subject=subject)
        iteration = 0
        all_tool_results: List[Dict[str, Any]] = []
        tools_override = self._determine_tools_for_request(history, user_message)

        while iteration < int(MAX_TOOL_ITERATIONS or 10):
            iteration += 1

            if iteration > 1:
                yield {"type": "iteration", "round": iteration, "message": f"AI 正在进行第 {iteration} 轮操作..."}

            delta_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
            streamed_llm_content = ""

            async def on_content_delta(text: str) -> None:
                nonlocal streamed_llm_content
                if not text:
                    return
                streamed_llm_content += str(text)
                await delta_queue.put(
                    {
                        "type": "text_delta",
                        "content": str(text),
                        "iteration": iteration,
                        "phase": "tool_decision",
                    }
                )

            async def on_reasoning_delta(text: str) -> None:
                if not text:
                    return
                await delta_queue.put(
                    {
                        "type": "thinking_delta",
                        "content": str(text),
                        "iteration": iteration,
                        "phase": "tool_decision",
                    }
                )

            yield {"type": "stream_start", "iteration": iteration, "phase": "tool_decision"}
            api_task = asyncio.create_task(
                self._call_api(
                    messages,
                    model=main_model,
                    include_tools=True,
                    tools_override=tools_override,
                    stream=True,
                    on_content_delta=on_content_delta,
                    on_reasoning_delta=on_reasoning_delta,
                )
            )
            while not api_task.done():
                try:
                    yield await asyncio.wait_for(delta_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue

            while not delta_queue.empty():
                yield delta_queue.get_nowait()

            try:
                result = await api_task
            except Exception as exc:
                logger.exception("chat_api_task_failed")
                yield {"type": "error", "content": str(exc or "api_error")}
                return

            if not result.get("success"):
                yield {"type": "error", "content": result.get("error") or "api_error"}
                return

            llm_content = str(result.get("content") or "")
            tool_calls = result.get("tool_calls")

            if isinstance(tool_calls, list) and tool_calls:
                display_content = llm_content
                if not display_content.strip():
                    tool_names: List[str] = []
                    for tc in tool_calls:
                        fn = tc.get("function") if isinstance(tc, dict) else {}
                        name = str((fn or {}).get("name") or "").strip()
                        if name:
                            tool_names.append(name)
                    display_content = (
                        f"（第 {iteration} 轮：调用工具 {', '.join(tool_names)}）"
                        if tool_names
                        else f"（第 {iteration} 轮：调用工具）"
                    )

                yield {
                    "type": "assistant",
                    "content": display_content,
                    "tool_calls": tool_calls,
                    "iteration": iteration,
                }

                prepared_calls = [self._prepare_tool_call(tc) for tc in tool_calls if isinstance(tc, dict)]
                tool_results_by_id: Dict[str, Dict[str, Any]] = {}
                for prepared in prepared_calls:
                    yield {
                        "type": "tool_start",
                        "tool_call_id": prepared.get("tool_call_id", ""),
                        "tool_name": prepared.get("tool_name", ""),
                        "arguments": prepared.get("arguments", {}),
                        "iteration": iteration,
                    }

                if self._can_execute_tool_calls_concurrently(prepared_calls):
                    executed = await asyncio.gather(
                        *[
                            self._execute_prepared_tool_call(
                                prepared,
                                sub_model=sub_model_effective,
                                user_id=uid,
                            )
                            for prepared in prepared_calls
                        ]
                    )
                else:
                    executed = []
                    for prepared in prepared_calls:
                        executed.append(
                            await self._execute_prepared_tool_call(
                                prepared,
                                sub_model=sub_model_effective,
                                user_id=uid,
                            )
                        )

                for item in executed:
                    tool_id = str(item.get("tool_call_id") or "").strip()
                    tool_name = str(item.get("tool_name") or "").strip()
                    tool_result = item.get("result")
                    yield {
                        "type": "tool_result",
                        "tool_call_id": tool_id,
                        "tool_name": tool_name,
                        "result": tool_result,
                        "iteration": iteration,
                    }

                    tool_results_by_id[tool_id] = {
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }

                tool_results: List[Dict[str, Any]] = []
                for prepared in prepared_calls:
                    tool_id = str(prepared.get("tool_call_id") or "").strip()
                    tool_result_msg = tool_results_by_id.get(tool_id)
                    if tool_result_msg:
                        tool_results.append(tool_result_msg)
                        all_tool_results.append(tool_result_msg)

                # Preserve tool-calling state for the next turn.
                messages.append({"role": "assistant", "content": llm_content, "tool_calls": tool_calls})
                messages.extend(tool_results)
                continue

            # No tool calls: model finished.
            if all_tool_results:
                if llm_content or streamed_llm_content:
                    final_content = llm_content or streamed_llm_content
                    if final_content and final_content.startswith(streamed_llm_content):
                        remaining = final_content[len(streamed_llm_content) :]
                        if remaining:
                            yield {"type": "text_delta", "content": remaining, "iteration": iteration}
                    elif final_content and final_content != streamed_llm_content:
                        yield {"type": "text_delta", "content": final_content, "iteration": iteration}
                    yield {"type": "assistant_final", "content": final_content, "total_iterations": iteration}
                    return

                yield {"type": "stream_start", "iteration": iteration}

                final_content = ""
                async for chunk in self._call_api_streaming(messages, model=main_model):
                    if chunk.get("type") == "text_delta":
                        final_content += str(chunk.get("content") or "")
                        yield chunk
                    elif chunk.get("type") == "error":
                        yield chunk
                        return

                if not final_content:
                    final_content = self._generate_fallback_response(all_tool_results)
                    yield {"type": "text_delta", "content": final_content}

                yield {"type": "assistant_final", "content": final_content, "total_iterations": iteration}
                return

            yield {"type": "stream_start", "iteration": iteration}
            if llm_content:
                # Avoid artificial latency; let the client render immediately.
                if llm_content.startswith(streamed_llm_content):
                    remaining = llm_content[len(streamed_llm_content) :]
                    if remaining:
                        yield {"type": "text_delta", "content": remaining}
                elif llm_content != streamed_llm_content:
                    yield {"type": "text_delta", "content": llm_content}
            yield {"type": "assistant_final", "content": llm_content, "total_iterations": iteration}
            return

        yield {
            "type": "assistant_final",
            "content": f"已完成 {MAX_TOOL_ITERATIONS} 轮操作。" + self._generate_fallback_response(all_tool_results),
            "total_iterations": iteration,
            "max_reached": True,
        }

_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
