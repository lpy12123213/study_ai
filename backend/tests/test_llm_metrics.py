from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.llm import metrics as llm_metrics
from scripts.replay_llm import convert_records


class LlmMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        llm_metrics.clear_llm_debug_calls()

    def test_recent_llm_calls_keeps_usage_summary(self) -> None:
        llm_metrics.record_llm_call(
            provider="openrouter",
            model="test-model",
            usage={"prompt_tokens": 3, "completion_tokens": 4, "cost_usd": 0.0012},
            stream=True,
            elapsed_s=1.23456,
            finish_reason="stop",
            request_id="req-1",
        )

        payload = llm_metrics.recent_llm_calls(limit=10)

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["totals"]["total_tokens"], 7)
        self.assertEqual(payload["totals"]["cost_usd"], 0.0012)
        self.assertEqual(payload["calls"][0]["usage"]["prompt_tokens"], 3)
        self.assertEqual(payload["calls"][0]["elapsed_s"], 1.2346)
        self.assertTrue(payload["calls"][0]["stream"])

    def test_convert_records_writes_replay_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "records"
            output = root / "fixtures" / "llm"
            source.mkdir(parents=True)
            (source / "record.json").write_text(
                json.dumps(
                    {
                        "request": {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                        "response": {"content": "ok", "finish_reason": "stop", "usage": {"total_tokens": 2}},
                    }
                ),
                encoding="utf-8",
            )

            summary = convert_records(source, output)

            self.assertEqual(summary["converted"], 1)
            fixtures = list(output.glob("*.json"))
            self.assertEqual(len(fixtures), 1)
            payload = json.loads(fixtures[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["namespace"], "llm")
            self.assertEqual(payload["response"]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
