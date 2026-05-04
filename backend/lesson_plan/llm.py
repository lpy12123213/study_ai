from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MAX_TOKENS
from backend.llm.runner import run_text


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
    # Default: do not artificially truncate.
    effective_max_tokens = max(64, int(max_tokens or LESSON_PLAN_MAX_TOKENS or 2000))
    return await run_text(
        messages=messages,
        model=str(model or "").strip(),
        temperature=float(temperature),
        max_tokens=effective_max_tokens,
        reasoning=reasoning,
        stream=False,
        raise_on_fail=bool(raise_on_fail),
        retries=retries,
        retry_env_vars=("LESSON_PLAN_LLM_RETRIES", "AGENT_LLM_RETRIES"),
        default_retries=6,
        timeout_env_vars=("LESSON_PLAN_LLM_TIMEOUT_S",),
        req_id_prefix="lpv2",
    )
