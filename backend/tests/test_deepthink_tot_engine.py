from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict, List, Sequence

from backend.generation.deepthink.tot_engine import ThoughtNode, ToTEngine


class ToTEngineConcurrencyTests(unittest.TestCase):
    def test_frontier_proposals_run_concurrently(self) -> None:
        active = 0
        max_active = 0

        async def propose(
            question: str,
            subject: str,
            path: Sequence[ThoughtNode],
            n: int,
        ) -> List[Dict[str, Any]]:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.02)
                depth = len([node for node in path if node.id != "root"])
                return [
                    {"thought": f"{path[-1].id}-a-{depth}", "reasoning": "r"},
                    {"thought": f"{path[-1].id}-b-{depth}", "reasoning": "r"},
                ][:n]
            finally:
                active -= 1

        async def evaluate(
            question: str,
            subject: str,
            path: Sequence[ThoughtNode],
            proposal: Dict[str, Any],
        ) -> Dict[str, Any]:
            return {"score": 9, "reasoning": "ok", "issues": []}

        async def run() -> None:
            engine = ToTEngine(
                question="1+1",
                subject="math",
                branch_factor=2,
                beam_width=2,
                max_depth=2,
                prune_threshold=0,
                timeout_seconds=10,
                propose_fn=propose,
                evaluate_fn=evaluate,
            )
            async for _ in engine.search():
                pass

        asyncio.run(run())

        self.assertGreaterEqual(max_active, 2)


if __name__ == "__main__":
    unittest.main()
