from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, Optional

from backend.agent.config import AgentConfig
from backend.agent.context import ContextManager
from backend.agent.executor import Executor
from backend.agent.memory import MemoryStore
from backend.agent.planner import Planner
from backend.agent.reflector import Reflector
from backend.agent.types import (
    ActionResults,
    AgentState,
    ExecutionPlan,
    ReflectionResult,
    StepResult,
    UserProfile,
    agent_event,
)


SYSTEM_INSTRUCTIONS = """你是一位严谨的自学资料编写老师。
目标：根据学生输入的知识点，生成一份可直接自学的 Markdown 学习材料。

硬性要求：
- 输出必须是 Markdown 纯文本
- 结构清晰：知识点讲解 → 例题（含详细步骤）→ 练习题（不含答案）
- 语言：中文
- 尽量减少无依据的编造；当信息来源不足时，明确标注“推断/建议”。
"""


def _chunk_text(text: str, *, chunk_size: int = 500) -> AsyncIterator[str]:
    async def _gen() -> AsyncIterator[str]:
        if not text:
            return
        for i in range(0, len(text), chunk_size):
            # Cooperative scheduling so the event loop can flush SSE.
            await asyncio.sleep(0)
            yield text[i : i + chunk_size]

    return _gen()


class AgentCore:
    """Plan-Act-Reflect agent core with streaming events."""

    def __init__(
        self,
        *,
        config: Optional[AgentConfig] = None,
        memory_store: Optional[MemoryStore] = None,
        context_manager: Optional[ContextManager] = None,
        planner: Optional[Planner] = None,
        executor: Optional[Executor] = None,
        reflector: Optional[Reflector] = None,
    ) -> None:
        self.config = config or AgentConfig.from_env()
        self.memory_store = memory_store or MemoryStore()
        self.context_manager = context_manager or ContextManager(config=self.config)
        self.planner = planner or Planner(config=self.config)
        self.executor = executor or Executor(config=self.config)
        self.reflector = reflector or Reflector(config=self.config)

        self.state: AgentState = AgentState.IDLE

    async def run(self, user_input: str, *, user_id: str = "anonymous") -> AsyncIterator[Dict[str, Any]]:
        """Main entry. Streams AgentEvents compatible with the frontend SSE handler."""

        user_input = (user_input or "").strip()
        if not user_input:
            yield agent_event("error", {"message": "Empty input"})
            return

        iteration = 0
        plan: Optional[ExecutionPlan] = None
        results = ActionResults()
        reflection: Optional[ReflectionResult] = None

        try:
            yield agent_event("thinking", {"content": "初始化上下文…"})
            self.state = AgentState.WAITING_TOOL
            yield agent_event("tool_call", {"name": "get_user_profile", "arguments": {"user_id": user_id}})
            profile = await self.memory_store.get_user_profile(user_id=user_id)

            ctx = self.context_manager.create_context(
                user_profile=profile,
                system_instructions=SYSTEM_INSTRUCTIONS,
                current_task=user_input,
            )
            self.context_manager.append_message(ctx, role="user", content=user_input)

            for iteration in range(self.config.max_iterations):
                results = ActionResults()
                self.state = AgentState.PLANNING
                yield agent_event("thinking", {"content": f"Plan 阶段：规划（第 {iteration + 1} 轮）…"})

                plan = await self.planner.plan(topic=user_input, user_profile=profile, context=ctx, iteration=iteration)
                if plan.rationale:
                    yield agent_event("thinking", {"content": plan.rationale})

                self.state = AgentState.ACTING
                yield agent_event("thinking", {"content": "Act 阶段：执行工具链…"})

                for step in plan.steps:
                    self.state = AgentState.WAITING_TOOL
                    yield agent_event("tool_call", {"name": step.tool, "arguments": step.arguments})
                    step_result = await self.executor.execute_step(step, context=ctx)
                    results.step_results.append(step_result)
                    self.context_manager.on_step_result(ctx, step=step, result=step_result)
                    if (
                        step_result.success
                        and step_result.tool in {"assemble_markdown", "revise_markdown"}
                        and isinstance(step_result.output, str)
                        and step_result.output.strip()
                    ):
                        results.artifacts["markdown"] = step_result.output.strip()

                self.state = AgentState.REFLECTING
                yield agent_event("thinking", {"content": "Reflect 阶段：自检与审查…"})
                reflection = await self.reflector.reflect(topic=user_input, plan=plan, results=results, context=ctx)

                if reflection.summary:
                    yield agent_event("thinking", {"content": reflection.summary})

                if reflection.passed:
                    break

                self.state = AgentState.ITERATING
                yield agent_event(
                    "thinking",
                    {
                        "content": "发现问题，准备迭代修正…\n"
                        + ("\n".join(f"- {x}" for x in (reflection.issues or [])[:6]) if reflection.issues else ""),
                    },
                )
                self.context_manager.on_reflection(ctx, reflection)

            markdown = results.artifacts.get("markdown") or ctx.working_memory.get("markdown") or ""
            if not isinstance(markdown, str):
                markdown = ""

            if not markdown:
                # Last-resort fallback to something readable.
                markdown = f"# 自学材料：{user_input}\n\n（生成结果为空，建议重试或提供更具体的描述）\n"

            yield agent_event("thinking", {"content": "输出 Markdown…"})
            async for chunk in _chunk_text(markdown, chunk_size=600):
                yield agent_event("content", {"content": chunk, "section": "markdown"})

            self.state = AgentState.COMPRESSING
            yield agent_event("tool_call", {"name": "compress_context", "arguments": {}})
            await self.context_manager.compress_if_needed(ctx)

            yield agent_event(
                "tool_call",
                {
                    "name": "update_user_profile",
                    "arguments": {
                        "user_id": user_id,
                        "topic": user_input,
                        "passed": bool(reflection.passed) if reflection else True,
                    },
                },
            )
            await self.memory_store.record_session(
                user_id=user_id,
                topic=user_input,
                passed=bool(reflection.passed) if reflection else True,
                issues=(reflection.issues if reflection else []),
            )

            self.state = AgentState.COMPLETED
            yield agent_event(
                "done",
                {
                    "material": {
                        "topic": user_input,
                        "markdown": markdown,
                        "iteration": iteration + 1,
                        "passed": bool(reflection.passed) if reflection else True,
                        "issues": reflection.issues if reflection else [],
                    }
                },
            )

        except Exception as exc:  # pragma: no cover (best-effort safety)
            self.state = AgentState.ERROR
            yield agent_event("error", {"message": str(exc)})

