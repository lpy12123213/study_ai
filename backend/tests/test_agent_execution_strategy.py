import types
import unittest
from typing import Any, Dict, List

from backend.agent.execution_strategy import ParallelStrategy, PerKnowledgePointStrategy
from backend.agent.types import ActionResults, CompressedContext, PlanStep, StepResult, UserProfile, agent_event


def _ctx(memory: Dict[str, Any] | None = None) -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="u1"),
        system_instructions="",
        current_task="task",
        working_memory=dict(memory or {}),
    )


async def _collect(stream) -> List[Dict[str, Any]]:  # type: ignore[no-untyped-def]
    out: List[Dict[str, Any]] = []
    async for item in stream:
        out.append(item)
    return out


class FakeDispatcher:
    def __init__(self, *, fail_ids: set[str] | None = None, abort_after: str = "", concurrency: int = 1) -> None:
        self.config = types.SimpleNamespace(subagent_concurrency=concurrency)
        self.fail_ids = fail_ids or set()
        self.abort_after = abort_after
        self.executed: List[str] = []
        self.summaries: Dict[str, str] = {}

    async def execute_concrete_step(self, *, ctx: CompressedContext, results: ActionResults, concrete_step: PlanStep):
        self.executed.append(concrete_step.id)
        if concrete_step.id in self.fail_ids:
            raise RuntimeError(f"boom:{concrete_step.id}")
        if self.abort_after and concrete_step.id == self.abort_after:
            ctx.working_memory["_abort_execution"] = True
        results.step_results.append(StepResult(step_id=concrete_step.id, tool=concrete_step.tool, success=True))
        yield agent_event("status", {"content": f"step:{concrete_step.id}"})
        yield agent_event("thinking", {"content": f"think:{concrete_step.id}"})
        yield agent_event("tool_result", {"step_id": concrete_step.id})

    def _get_split_knowledge_points(self, ctx: CompressedContext) -> List[str]:
        split = ctx.working_memory.get("split_knowledge_points")
        return list(split.get("knowledge_points") or []) if isinstance(split, dict) else []

    def _expand_foreach_step(self, step: PlanStep, *, kp: str) -> PlanStep:
        args = dict(step.arguments or {})
        args["knowledge_points"] = [kp]
        return PlanStep(id=f"{step.id}-{kp}", title=f"{step.title}:{kp}", tool=step.tool, arguments=args)

    async def _summarize_subagent(self, _ctx: CompressedContext, kp: str) -> str:
        return f"summary:{kp}"

    def _store_subagent_summary(self, _ctx: CompressedContext, kp: str, summary: str) -> None:
        self.summaries[kp] = summary


class AgentExecutionStrategyTests(unittest.IsolatedAsyncioTestCase):
    async def test_step_block_stops_after_abort_flag(self) -> None:
        strategy = ParallelStrategy()
        dispatcher = FakeDispatcher(abort_after="one")
        results = ActionResults()
        ctx = _ctx()

        events = await _collect(
            strategy.execute_step_block(
                dispatcher=dispatcher,
                ctx=ctx,
                results=results,
                steps=[
                    PlanStep(id="one", title="One", tool="t"),
                    PlanStep(id="two", title="Two", tool="t"),
                ],
            )
        )

        self.assertEqual(dispatcher.executed, ["one"])
        self.assertEqual(
            [event["data"]["step_id"] for event in events if event.get("event") == "tool_result"],
            ["one"],
        )

    async def test_parallel_group_reports_partial_failure(self) -> None:
        strategy = ParallelStrategy()
        dispatcher = FakeDispatcher(fail_ids={"bad"})
        results = ActionResults()
        ctx = _ctx()

        events = await _collect(
            strategy.execute_step_block(
                dispatcher=dispatcher,
                ctx=ctx,
                results=results,
                steps=[
                    PlanStep(id="ok", title="Ok", tool="tool", parallel_group="g"),
                    PlanStep(id="bad", title="Bad", tool="tool", parallel_group="g"),
                ],
            )
        )

        self.assertEqual(set(dispatcher.executed), {"ok", "bad"})
        self.assertTrue(any(event.get("event") == "tool_result" for event in events))
        self.assertTrue(any(event.get("event") == "error" and "Parallel step failed" in event["data"]["message"] for event in events))

    async def test_foreach_strategy_runs_per_knowledge_point_and_stores_summary(self) -> None:
        strategy = PerKnowledgePointStrategy()
        dispatcher = FakeDispatcher(concurrency=1)
        results = ActionResults()
        ctx = _ctx({"split_knowledge_points": {"knowledge_points": ["函数", "导数"]}})

        events = await _collect(
            strategy.execute_foreach_block(
                dispatcher=dispatcher,
                ctx=ctx,
                results=results,
                block=[PlanStep(id="research", title="研究", tool="web_search_knowledge")],
                fallback_kp="",
            )
        )

        self.assertEqual(dispatcher.executed, ["research-函数", "research-导数"])
        self.assertEqual(dispatcher.summaries, {"函数": "summary:函数", "导数": "summary:导数"})
        self.assertEqual(len([event for event in events if event.get("event") == "subagent_start"]), 2)

    async def test_foreach_parallel_tags_subagent_events(self) -> None:
        strategy = PerKnowledgePointStrategy()
        dispatcher = FakeDispatcher(concurrency=3)
        results = ActionResults()
        ctx = _ctx({"split_knowledge_points": {"knowledge_points": ["函数", "导数", "积分"]}})

        events = await _collect(
            strategy.execute_foreach_block(
                dispatcher=dispatcher,
                ctx=ctx,
                results=results,
                block=[PlanStep(id="research", title="研究", tool="web_search_knowledge")],
                fallback_kp="",
            )
        )

        starts = {e["data"]["subagent_id"]: e for e in events if e.get("event") == "subagent_start"}
        ends = {e["data"]["subagent_id"]: e for e in events if e.get("event") == "subagent_end"}
        self.assertEqual(set(starts), {"sa-0", "sa-1", "sa-2"})
        self.assertEqual(set(ends), {"sa-0", "sa-1", "sa-2"})

        # start/end 契约字段齐全，index 每个 kp 唯一。
        for sid, evt in starts.items():
            d = evt["data"]
            self.assertEqual(d["subagent_id"], sid)
            self.assertEqual(d["index"], int(sid.split("-")[1]))
            self.assertEqual(d["total"], 3)
            self.assertEqual(d["kind"], "knowledge_research")
            self.assertIn("knowledge_point", d)
            self.assertIn("content", d)
        for sid, evt in ends.items():
            d = evt["data"]
            self.assertEqual(d["subagent_id"], sid)
            self.assertEqual(d["index"], int(sid.split("-")[1]))
            self.assertEqual(d["total"], 3)
            self.assertEqual(d["kind"], "knowledge_research")
            self.assertIn("knowledge_point", d)

        # 下游 tool_result/status/thinking 归属正确子代理，无跨 kp 串归属。
        kp_by_sid = {sid: evt["data"]["knowledge_point"] for sid, evt in starts.items()}
        for e in events:
            d = e.get("data") or {}
            sid = d.get("subagent_id")
            if sid is None:
                continue
            self.assertIn(sid, kp_by_sid)
            self.assertEqual(d.get("knowledge_point"), kp_by_sid[sid])
            if e.get("event") == "tool_result":
                self.assertEqual(d["step_id"], f"research-{kp_by_sid[sid]}")

    async def test_foreach_serial_tags_subagent_events(self) -> None:
        strategy = PerKnowledgePointStrategy()
        dispatcher = FakeDispatcher(concurrency=1)
        results = ActionResults()
        ctx = _ctx({"split_knowledge_points": {"knowledge_points": ["函数", "导数"]}})

        events = await _collect(
            strategy.execute_foreach_block(
                dispatcher=dispatcher,
                ctx=ctx,
                results=results,
                block=[PlanStep(id="research", title="研究", tool="web_search_knowledge")],
                fallback_kp="",
            )
        )

        starts = {e["data"]["subagent_id"]: e for e in events if e.get("event") == "subagent_start"}
        ends = {e["data"]["subagent_id"]: e for e in events if e.get("event") == "subagent_end"}
        self.assertEqual(set(starts), {"sa-0", "sa-1"})
        self.assertEqual(set(ends), {"sa-0", "sa-1"})

        for sid, evt in starts.items():
            d = evt["data"]
            self.assertEqual(d["index"], int(sid.split("-")[1]))
            self.assertEqual(d["total"], 2)
            self.assertEqual(d["kind"], "knowledge_research")
        for sid, evt in ends.items():
            d = evt["data"]
            self.assertEqual(d["index"], int(sid.split("-")[1]))
            self.assertEqual(d["total"], 2)
            self.assertEqual(d["kind"], "knowledge_research")

        kp_by_sid = {sid: evt["data"]["knowledge_point"] for sid, evt in starts.items()}
        for e in events:
            d = e.get("data") or {}
            sid = d.get("subagent_id")
            if sid is None:
                continue
            self.assertIn(sid, kp_by_sid)
            self.assertEqual(d.get("knowledge_point"), kp_by_sid[sid])
            if e.get("event") == "tool_result":
                self.assertEqual(d["step_id"], f"research-{kp_by_sid[sid]}")

    def test_tag_subagent_event(self) -> None:
        from backend.agent.execution_strategy import _tag_subagent_event

        # 数据注入 + 不修改源事件。
        source = {"event": "status", "data": {"content": "x"}}
        out = _tag_subagent_event(source, "sa-0", "函数")
        self.assertEqual(out["data"]["subagent_id"], "sa-0")
        self.assertEqual(out["data"]["knowledge_point"], "函数")
        self.assertEqual(out["data"]["content"], "x")
        self.assertIsNot(out, source)
        self.assertIsNot(out["data"], source["data"])
        self.assertEqual(source["data"], {"content": "x"})
        self.assertNotIn("subagent_id", source["data"])
        self.assertNotIn("knowledge_point", source["data"])

        # 空 kp 时不注入 knowledge_point。
        out2 = _tag_subagent_event(source, "sa-1", "")
        self.assertEqual(out2["data"]["subagent_id"], "sa-1")
        self.assertNotIn("knowledge_point", out2["data"])

        # 非 dict data（None / 缺失）透传仍能注入。
        out3 = _tag_subagent_event({"event": "status", "data": None}, "sa-2", "kp")
        self.assertEqual(out3["data"], {"subagent_id": "sa-2", "knowledge_point": "kp"})
        out4 = _tag_subagent_event({"event": "status"}, "sa-3", "kp")
        self.assertEqual(out4["data"], {"subagent_id": "sa-3", "knowledge_point": "kp"})
