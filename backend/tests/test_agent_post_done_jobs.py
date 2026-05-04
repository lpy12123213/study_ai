import asyncio
import time
import unittest

from backend.agent.config import AgentConfig
from backend.agent.core import AgentCore
from backend.agent.memory.semantic_store import SemanticDoc


class _SlowSemanticStore:
    def __init__(self) -> None:
        self.called = False

    async def upsert(self, *, user_id: str, docs: list[SemanticDoc]) -> None:
        await asyncio.sleep(0.03)
        self.called = True
        self.user_id = user_id
        self.docs = docs


class TestAgentPostDoneJobs(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_upsert_is_scheduled_without_blocking(self) -> None:
        store = _SlowSemanticStore()
        agent = AgentCore(
            config=AgentConfig(planner_model="", reflector_model=""),
            semantic_store=store,  # type: ignore[arg-type]
        )
        docs = [SemanticDoc(doc_id="d1", text="hello", metadata={})]

        started = time.perf_counter()
        task = agent._schedule_semantic_upsert(user_id="u1", docs=docs, timeout_s=1.0)
        elapsed = time.perf_counter() - started

        self.assertIsNotNone(task)
        self.assertLess(elapsed, 0.02)
        self.assertFalse(store.called)
        self.assertEqual(len(agent._post_done_tasks), 1)

        await task
        await asyncio.sleep(0)

        self.assertTrue(store.called)
        self.assertEqual(store.user_id, "u1")
        self.assertEqual(store.docs, docs)
        self.assertEqual(len(agent._post_done_tasks), 0)


if __name__ == "__main__":
    unittest.main()
