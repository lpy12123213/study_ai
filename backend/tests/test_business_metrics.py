import os
import unittest
from unittest.mock import patch

from backend.core import business_metrics


class TestBusinessMetrics(unittest.TestCase):
    def test_recorders_are_noops_when_disabled(self) -> None:
        with patch.dict(os.environ, {"PROMETHEUS_METRICS_ENABLED": "0"}):
            business_metrics.record_llm_usage(
                provider="test",
                model="model",
                usage={"prompt_tokens": 2, "completion_tokens": 3},
            )
            business_metrics.record_tool_call(name="tool", success=True)
            business_metrics.record_task_terminal(task_type="type", status="completed")


if __name__ == "__main__":
    unittest.main()
