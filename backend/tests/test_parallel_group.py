import asyncio
import time
import unittest

from backend.agent.context import ContextManager
from backend.agent.core import AgentCore
from backend.agent.types import ActionResults, PlanStep, StepResult, UserProfile


class _SleepyExecutor:
    def __init__(self) -> None:
        self.starts = {}

    async def execute_step(self, step: PlanStep, *, context, emit_event=None) -> StepResult:  # type: ignore[override]
        # Record as early as possible to check overlap.
        self.starts[step.id] = time.monotonic()
        delay = float((step.arguments or {}).get("delay_s") or 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        return StepResult(step_id=step.id, tool=step.tool, success=True, output={"ok": True})


class TestParallelGroup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ctx_mgr = ContextManager()
        self.executor = _SleepyExecutor()
        self.core = AgentCore(executor=self.executor, context_manager=self.ctx_mgr)
        self.ctx = self.ctx_mgr.create_context(
            user_profile=UserProfile(user_id="u"),
            system_instructions="",
            current_task="t",
        )
        self.results = ActionResults()

    async def _drain(self, steps):
        async for _evt in self.core._execute_step_block(ctx=self.ctx, results=self.results, steps=steps):
            pass

    async def test_parallel_group_runs_concurrently(self):
        steps = [
            PlanStep(
                id="a",
                title="A",
                tool="sleep_a",
                arguments={"delay_s": 0.25},
                parallel_group="g1",
            ),
            PlanStep(
                id="b",
                title="B",
                tool="sleep_b",
                arguments={"delay_s": 0.25},
                parallel_group="g1",
            ),
        ]
        t0 = time.monotonic()
        await self._drain(steps)
        elapsed = time.monotonic() - t0

        # Should be ~0.25s, not ~0.50s.
        self.assertLess(elapsed, 0.42)

        t_a = self.executor.starts["a"]
        t_b = self.executor.starts["b"]
        self.assertLess(abs(t_a - t_b), 0.12)

    async def test_non_parallel_steps_run_sequentially(self):
        steps = [
            PlanStep(id="a2", title="A2", tool="sleep_a2", arguments={"delay_s": 0.2}),
            PlanStep(id="b2", title="B2", tool="sleep_b2", arguments={"delay_s": 0.2}),
        ]
        t0 = time.monotonic()
        await self._drain(steps)
        elapsed = time.monotonic() - t0

        self.assertGreater(elapsed, 0.34)

        t_a = self.executor.starts["a2"]
        t_b = self.executor.starts["b2"]
        self.assertGreater(t_b - t_a, 0.15)
