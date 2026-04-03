from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from backend.chat.llm_mixin import ChatLLMMixin
from backend.chat.tools_mixin import ChatToolsMixin
from backend.core.settings import API_TIMEOUT, MAIN_MODEL, MAX_TOOL_ITERATIONS


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
            except Exception:
                continue

        if responses:
            return "\n\n".join(responses) + "\n\n请查看上方的详细结果。如需继续操作，请告诉我。"
        return "操作已完成，请查看上方的工具执行结果。"

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

        endpoint = self._resolve_chat_endpoint(main_model)
        if not endpoint.get("api_key"):
            provider = endpoint.get("provider")
            yield {"type": "error", "content": f"未配置 {provider} API Key（当前模型: {main_model}）"}
            return

        messages = self._build_messages(history, user_message, subject=subject)
        iteration = 0
        all_tool_results: List[Dict[str, Any]] = []
        tools_override = self._determine_tools_for_request(history, user_message)

        async with httpx.AsyncClient(timeout=httpx.Timeout(float(API_TIMEOUT or 30), connect=30.0)) as client:
            while iteration < int(MAX_TOOL_ITERATIONS or 10):
                iteration += 1

                if iteration > 1:
                    yield {"type": "iteration", "round": iteration, "message": f"AI 正在进行第 {iteration} 轮操作..."}

                result = await self._call_api(
                    client,
                    messages,
                    model=main_model,
                    include_tools=True,
                    tools_override=tools_override,
                )

                if not result.get("success"):
                    yield {"type": "error", "content": result.get("error") or "api_error"}
                    return

                data = result.get("data") or {}
                choice = (data.get("choices") or [{}])[0] if isinstance(data.get("choices"), list) else {}
                message = choice.get("message", {}) if isinstance(choice, dict) else {}

                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    if len(tool_calls) > 3:
                        tool_calls = tool_calls[:3]

                    assistant_content = str(message.get("content") or "")
                    if not assistant_content.strip():
                        tool_names: List[str] = []
                        for tc in tool_calls:
                            fn = tc.get("function") if isinstance(tc, dict) else {}
                            name = str((fn or {}).get("name") or "").strip()
                            if name:
                                tool_names.append(name)
                        assistant_content = (
                            f"（第 {iteration} 轮：调用工具 {', '.join(tool_names)}）"
                            if tool_names
                            else f"（第 {iteration} 轮：调用工具）"
                        )

                    yield {
                        "type": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls,
                        "iteration": iteration,
                    }

                    tool_results: List[Dict[str, Any]] = []
                    for tool_call in tool_calls:
                        fn = tool_call.get("function") if isinstance(tool_call, dict) else {}
                        tool_name = str((fn or {}).get("name") or "").strip()
                        tool_id = str(tool_call.get("id") or "").strip()
                        raw_args = (fn or {}).get("arguments") if isinstance(fn, dict) else {}
                        if isinstance(raw_args, str):
                            try:
                                tool_args = json.loads(raw_args)
                            except Exception:
                                tool_args = {}
                        else:
                            tool_args = raw_args if isinstance(raw_args, dict) else {}
                        tool_args = self._coerce_tool_args(tool_name, tool_args)

                        yield {
                            "type": "tool_start",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "iteration": iteration,
                        }

                        tool_result = await self.execute_tool(
                            tool_name,
                            tool_args,
                            sub_model=sub_model_effective,
                            user_id=uid,
                        )
                        yield {
                            "type": "tool_result",
                            "tool_call_id": tool_id,
                            "tool_name": tool_name,
                            "result": tool_result,
                            "iteration": iteration,
                        }

                        tool_result_msg = {
                            "tool_call_id": tool_id,
                            "role": "tool",
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                        tool_results.append(tool_result_msg)
                        all_tool_results.append(tool_result_msg)

                    messages.append(message)
                    messages.extend(tool_results)
                    continue

                # No tool calls: model finished.
                if all_tool_results:
                    yield {"type": "stream_start", "iteration": iteration}

                    final_content = ""
                    async for chunk in self._call_api_streaming(client, messages, model=main_model):
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

                final_content = str(message.get("content") or "")
                yield {"type": "stream_start", "iteration": iteration}
                if final_content:
                    # Avoid artificial latency; let the client render immediately.
                    yield {"type": "text_delta", "content": final_content}
                yield {"type": "assistant_final", "content": final_content, "total_iterations": iteration}
                return

            yield {
                "type": "assistant_final",
                "content": f"已完成 {MAX_TOOL_ITERATIONS} 轮操作。"
                + self._generate_fallback_response(all_tool_results),
                "total_iterations": iteration,
                "max_reached": True,
            }


chat_service = ChatService()
