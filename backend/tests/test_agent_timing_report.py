import unittest

from backend.agent.streaming import build_timing_report
from backend.agent.types import CompressedContext, UserProfile


class TestAgentTimingReport(unittest.TestCase):
    def test_timing_report_keeps_bounded_tool_summary(self) -> None:
        ctx = CompressedContext(
            user_profile=UserProfile(user_id="u1"),
            system_instructions="",
            current_task="task",
            working_memory={
                "_tool_timings": [
                    {"name": f"tool_{i}", "elapsed_ms": 1000 - i}
                    for i in range(12)
                ],
            },
        )

        report = build_timing_report(ctx=ctx, per_kp_report=[])

        self.assertEqual(report["tool_calls"], 12)
        self.assertEqual(len(report["by_tool"]), 8)
        self.assertEqual(report["by_tool_omitted"], 4)


if __name__ == "__main__":
    unittest.main()
