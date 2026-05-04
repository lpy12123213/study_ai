from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol

from backend.agent.types import ActionResults, CompressedContext, PlanStep, agent_event
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


class ExecutionStrategy(Protocol):
    async def execute_step_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        ...

    async def execute_foreach_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        fallback_kp: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        ...


class SequentialStrategy:
    async def execute_step_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        for step in steps:
            if bool(ctx.working_memory.get("_abort_execution")):
                return
            async for evt in dispatcher.execute_concrete_step(ctx=ctx, results=results, concrete_step=step):
                yield evt

    async def execute_foreach_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        fallback_kp: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        async for evt in self.execute_step_block(dispatcher=dispatcher, ctx=ctx, results=results, steps=block):
            yield evt


class ParallelStrategy(SequentialStrategy):
    def _chunk_by_parallel_group(self, steps: List[PlanStep]) -> List[List[PlanStep]]:
        groups: List[List[PlanStep]] = []
        i = 0
        while i < len(steps):
            pg = str(getattr(steps[i], "parallel_group", "") or "").strip()
            if not pg:
                groups.append([steps[i]])
                i += 1
                continue
            chunk: List[PlanStep] = []
            while i < len(steps):
                cur_pg = str(getattr(steps[i], "parallel_group", "") or "").strip()
                if cur_pg != pg:
                    break
                chunk.append(steps[i])
                i += 1
            groups.append(chunk)
        return groups

    async def _execute_parallel_steps(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

        async def _run_one(step: PlanStep) -> None:
            try:
                async for evt in dispatcher.execute_concrete_step(ctx=ctx, results=results, concrete_step=step):
                    await queue.put(evt)
            except Exception as exc:  # pragma: no cover (best-effort safety)
                logger.exception("agent_parallel_step_failed", extra={"tool": str(getattr(step, "tool", "") or "")})
                await queue.put(agent_event("error", {"message": f"Parallel step failed ({step.tool}): {exc}"}))
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(_run_one(step)) for step in steps]
        finished = 0
        while finished < len(tasks):
            item = await queue.get()
            if item is None:
                finished += 1
                continue
            yield item

        for task in tasks:
            try:
                await task
            except Exception:
                logger.exception("agent_parallel_task_join_failed")

    async def execute_step_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        steps: List[PlanStep],
    ) -> AsyncIterator[Dict[str, Any]]:
        for chunk in self._chunk_by_parallel_group(steps):
            if bool(ctx.working_memory.get("_abort_execution")):
                return
            if len(chunk) <= 1:
                async for evt in dispatcher.execute_concrete_step(ctx=ctx, results=results, concrete_step=chunk[0]):
                    yield evt
                continue
            async for evt in self._execute_parallel_steps(dispatcher=dispatcher, ctx=ctx, results=results, steps=chunk):
                yield evt


class PerKnowledgePointStrategy(ParallelStrategy):
    async def _run_subagent(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        kp: str,
        sem: asyncio.Semaphore,
        queue: "asyncio.Queue[Optional[Dict[str, Any]]]",
    ) -> None:
        try:
            async with sem:
                await queue.put(
                    agent_event(
                        "subagent_start",
                        {
                            "knowledge_point": kp,
                            "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}",
                        },
                    )
                )
                await queue.put(agent_event("status", {"content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}"}))

                concrete_block = [dispatcher._expand_foreach_step(step, kp=kp) for step in block]
                async for evt in self.execute_step_block(dispatcher=dispatcher, ctx=ctx, results=results, steps=concrete_block):
                    await queue.put(evt)

                summary = await dispatcher._summarize_subagent(ctx, kp)
                if summary:
                    dispatcher._store_subagent_summary(ctx, kp, summary)
                    await queue.put(agent_event("status", {"content": f"SubAgent 摘要（{kp}）：{summary}"}))

                await queue.put(
                    agent_event(
                        "subagent_end",
                        {
                            "knowledge_point": kp,
                            "content": f"SubAgent 完成：已收集该知识点的资料。\n当前知识点：{kp}",
                        },
                    )
                )
                await queue.put(agent_event("status", {"content": f"SubAgent 完成：已收集该知识点的资料。\n当前知识点：{kp}"}))
        except Exception as exc:  # pragma: no cover (best-effort safety)
            logger.exception("agent_subagent_failed", extra={"knowledge_point": kp})
            await queue.put(agent_event("error", {"message": f"SubAgent 运行失败（{kp}）：{exc}"}))
        finally:
            await queue.put(None)

    async def execute_foreach_block(
        self,
        *,
        dispatcher: Any,
        ctx: CompressedContext,
        results: ActionResults,
        block: List[PlanStep],
        fallback_kp: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        kps = dispatcher._get_split_knowledge_points(ctx)
        if not kps and fallback_kp:
            kps = [fallback_kp]

        positive_limits = [int(getattr(step, "foreach_limit", 0) or 0) for step in block]
        positive_limits = [limit for limit in positive_limits if limit > 0]
        if positive_limits:
            kps = kps[: max(1, min(positive_limits))]

        if not kps:
            async for evt in self.execute_step_block(dispatcher=dispatcher, ctx=ctx, results=results, steps=block):
                yield evt
            return

        subagent_concurrency = max(1, int(getattr(dispatcher.config, "subagent_concurrency", 3) or 3))
        subagent_concurrency = min(subagent_concurrency, len(kps))

        try:
            opts = ctx.working_memory.get("study_options")
            opts = dict(opts) if isinstance(opts, dict) else {}
            if str(opts.get("preset") or "").strip().lower() == "research":
                subagent_concurrency = min(subagent_concurrency, 2)
        except (AttributeError, TypeError, ValueError):
            logger.debug("agent_subagent_concurrency_adjust_failed", exc_info=True)

        if subagent_concurrency <= 1 or len(kps) <= 1:
            for kp in kps:
                yield agent_event(
                    "subagent_start",
                    {"knowledge_point": kp, "content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}"},
                )
                yield agent_event("status", {"content": f"SubAgent 启动：深挖该知识点的资料与题型。\n当前知识点：{kp}"})

                concrete_block = [dispatcher._expand_foreach_step(step, kp=kp) for step in block]
                async for evt in self.execute_step_block(dispatcher=dispatcher, ctx=ctx, results=results, steps=concrete_block):
                    yield evt

                summary = await dispatcher._summarize_subagent(ctx, kp)
                if summary:
                    dispatcher._store_subagent_summary(ctx, kp, summary)
                    yield agent_event("status", {"content": f"SubAgent 摘要（{kp}）：{summary}"})

                yield agent_event(
                    "subagent_end",
                    {
                        "knowledge_point": kp,
                        "content": f"SubAgent 完成：已收集该知识点的资料，准备进入下一个。\n当前知识点：{kp}",
                    },
                )
                yield agent_event("status", {"content": f"SubAgent 完成：已收集该知识点的资料，准备进入下一个。\n当前知识点：{kp}"})
            return

        yield agent_event("status", {"content": f"SubAgent 并行模式：共 {len(kps)} 个知识点，最大并发 {subagent_concurrency}。"})

        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        sem = asyncio.Semaphore(subagent_concurrency)
        tasks = [
            asyncio.create_task(self._run_subagent(dispatcher=dispatcher, ctx=ctx, results=results, block=block, kp=kp, sem=sem, queue=queue))
            for kp in kps
        ]
        finished = 0
        while finished < len(tasks):
            item = await queue.get()
            if item is None:
                finished += 1
                continue
            yield item

        for task in tasks:
            try:
                await task
            except Exception:
                logger.exception("agent_parallel_task_join_failed")
