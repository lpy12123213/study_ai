from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetryPolicy:
    """Central retry-delay policy for LLM HTTP calls."""

    min_delay_s: float = 0.5
    base_delay_s: float = 0.9
    jitter_s: float = 0.6
    max_delay_s: float = 8.0
    adaptation_delay_s: float = 0.2
    invalid_json_base_s: float = 0.4
    invalid_json_jitter_s: float = 0.8
    invalid_json_max_s: float = 3.0

    def http_retry_delay(self, resp: Any, *, attempt: int) -> float:
        retry_after_s = self._retry_after_header(resp)
        if retry_after_s > 0:
            return retry_after_s
        return self.retryable_status_delay(attempt=attempt)

    def retryable_status_delay(self, *, attempt: int) -> float:
        attempt_n = max(0, int(attempt or 0))
        delay = (2**attempt_n) * max(0.0, float(self.base_delay_s)) + random.random() * max(
            0.0, float(self.jitter_s)
        )
        return min(max(0.0, float(self.max_delay_s)), max(float(self.min_delay_s), delay))

    def adaptation_delay(self) -> float:
        return max(0.0, float(self.adaptation_delay_s))

    def invalid_json_delay(self) -> float:
        delay = max(0.0, float(self.invalid_json_base_s)) + random.random() * max(
            0.0, float(self.invalid_json_jitter_s)
        )
        return min(max(0.0, float(self.invalid_json_max_s)), max(0.0, delay))

    def _retry_after_header(self, resp: Any) -> float:
        try:
            value = float((resp.headers.get("retry-after") or "").strip())
        except (AttributeError, TypeError, ValueError):
            value = 0.0
        return value if value > 0 else 0.0


DEFAULT_RETRY_POLICY = RetryPolicy()
