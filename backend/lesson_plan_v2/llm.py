from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from backend.core import llm_console
from backend.core.llm_client import (
    cap_max_tokens_for_messages,
    get_llm_api_key_override,
    get_moonshot_api_key_override,
)
from backend.core.settings import (
    API_TIMEOUT,
    LLM_PROVIDER_PINNED,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_PROVIDER,
    LESSON_PLAN_TEMPERATURE,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
)


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
    provider = str(LESSON_PLAN_PROVIDER or "").strip().lower() or "openrouter"
    base_url = str(LESSON_PLAN_BASE_URL or "").strip().rstrip("/")
    api_key = str(get_llm_api_key_override() or LESSON_PLAN_API_KEY or "").strip()

    normalized_model = str(model or "").strip()
    model_lower = normalized_model.lower()
    moonshot_key = str(get_moonshot_api_key_override() or MOONSHOT_API_KEY or "").strip()
    moonshot_base_url = str(MOONSHOT_BASE_URL or "").strip().rstrip("/")

    if provider == "moonshot" or (
        not bool(LLM_PROVIDER_PINNED)
        and provider == "openrouter"
        and moonshot_key
        and (
            model_lower.startswith("moonshotai/")
            or model_lower.startswith("kimi-")
            or model_lower.startswith("moonshot-")
        )
    ):
        provider = "moonshot"
        api_key = moonshot_key or api_key
        base_url = moonshot_base_url or base_url
        if "/" in normalized_model:
            normalized_model = normalized_model.split("/")[-1]

    if not api_key:
        if raise_on_fail:
            raise RuntimeError("llm_not_configured")
        return ""

    req_id_base = f"lpv2-{uuid.uuid4().hex[:8]}"

    def _elapsed_s(start_ts: float) -> float:
        if not start_ts:
            return 0.0
        try:
            return max(0.0, time.time() - float(start_ts))
        except Exception:
            return 0.0

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

    def _resp_error(resp: Optional[httpx.Response]) -> str:
        if resp is None:
            return ""
        msg = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    msg = str(err.get("message") or err.get("detail") or err.get("error") or "").strip()
                elif isinstance(err, str):
                    msg = err.strip()
                if not msg:
                    msg = str(data.get("message") or data.get("detail") or "").strip()
        except Exception:
            msg = ""
        if not msg:
            try:
                msg = str(resp.text or "").strip()
            except Exception:
                msg = ""
        msg = msg.replace("\n", " ").strip() if msg else ""
        return msg[:260]

    # Default: do not artificially truncate.
    effective_max_tokens = max(64, int(max_tokens or LESSON_PLAN_MAX_TOKENS or 2000))

    last_error = ""
    for attempt in range(_max_retries()):
        req_id = f"{req_id_base}-{attempt + 1}"

        msg_capped = cap_max_tokens_for_messages(messages, max_tokens=24000)
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=normalized_model,
            stream=False,
            temperature=float(temperature),
            max_tokens=effective_max_tokens,
            base_url=base_url,
        )

        resp: Optional[httpx.Response] = None
        try:
            payload: Dict[str, Any] = {
                "model": normalized_model,
                "messages": msg_capped,
                "max_tokens": effective_max_tokens,
                "temperature": float(temperature),
            }
            if reasoning is not None:
                payload["reasoning"] = reasoning

            async with httpx.AsyncClient(timeout=httpx.Timeout(float(API_TIMEOUT or 60), connect=30.0)) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )

            if resp.status_code != 200:
                detail = _resp_error(resp)
                last_error = f"api_error status={resp.status_code} detail={detail}"
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if attempt < _max_retries() - 1:
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                if raise_on_fail:
                    raise RuntimeError(last_error)
                return ""

            data = resp.json()
            choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
            msg = choice0.get("message", {}) if isinstance(choice0, dict) else {}
            content = str(msg.get("content") or "") if isinstance(msg, dict) else ""
            llm_console.log_delta(req_id=req_id, channel="content", text=content)
            llm_console.log_end(
                req_id=req_id,
                elapsed_s=_elapsed_s(start_ts),
                finish_reason=str(choice0.get("finish_reason") or "") if isinstance(choice0, dict) else "",
                usage=dict(data.get("usage") or {}) if isinstance(data, dict) else {},
                content_chars=len(content),
            )
            return content
        except Exception as exc:
            last_error = f"request_error: {exc}"
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
            if attempt < _max_retries() - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
            return ""

    if raise_on_fail:
        raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error or 'unknown'}")
    return ""
