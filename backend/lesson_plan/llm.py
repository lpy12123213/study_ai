from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from backend.llm.client import chat_completion_text
from backend.core.settings import LESSON_PLAN_MAX_TOKENS


async def call_llm_text(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    reasoning: Optional[Dict[str, Any]] = None,
    raise_on_fail: bool = True,
    retries: Optional[int] = None,
) -> str:
    def _max_retries() -> int:
        raw = str(
            retries
            if retries is not None
            else os.getenv("LESSON_PLAN_LLM_RETRIES") or os.getenv("AGENT_LLM_RETRIES") or "6"
        ).strip()
        try:
            v = int(raw)
        except Exception:
            v = 6
        return max(1, min(v, 10))

    # Default: do not artificially truncate.
    effective_max_tokens = max(64, int(max_tokens or LESSON_PLAN_MAX_TOKENS or 2000))
    timeout_s: Optional[float] = None
    timeout_raw = str(os.getenv("LESSON_PLAN_LLM_TIMEOUT_S") or "").strip()
    if timeout_raw:
        try:
            timeout_s = float(timeout_raw)
        except Exception:
            timeout_s = None
    return await chat_completion_text(
        messages=messages,
        model=str(model or "").strip(),
        temperature=float(temperature),
        max_tokens=effective_max_tokens,
        reasoning=reasoning,
        stream=False,
        raise_on_fail=bool(raise_on_fail),
        retries=_max_retries(),
        timeout_s=timeout_s,
        req_id_prefix="lpv2",
    )
