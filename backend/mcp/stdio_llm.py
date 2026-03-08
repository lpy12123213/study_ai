from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from typing import Any, Dict, List

import httpx

from backend.core import llm_console
from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_PROVIDER,
    LLM_PROVIDER_PINNED,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
)


def extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip().strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def call_llm_text(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    provider = str(LESSON_PLAN_PROVIDER or "").strip().lower() or "openrouter"
    base_url = str(LESSON_PLAN_BASE_URL or "").strip().rstrip("/")
    api_key = str(LESSON_PLAN_API_KEY or "").strip()

    normalized_model = str(model or "").strip()
    model_lower = normalized_model.lower()
    moonshot_key = str(MOONSHOT_API_KEY or "").strip()
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
        return ""

    req_id_base = f"mcp-stdio-{uuid.uuid4().hex[:8]}"

    def _elapsed_s(start_ts: float) -> float:
        if not start_ts:
            return 0.0
        try:
            return max(0.0, time.time() - float(start_ts))
        except Exception:
            return 0.0

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": normalized_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
        payload["temperature"] = 1.0

    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    timeout_s = float(API_TIMEOUT or 120)

    for attempt in range(3):
        req_id = f"{req_id_base}-{attempt + 1}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=normalized_model,
            stream=False,
            temperature=float(payload.get("temperature") or 0.0),
            max_tokens=int(payload.get("max_tokens") or 0),
            base_url=base_url,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if resp.status_code in retry_statuses and attempt < 2:
                retry_after = (resp.headers.get("retry-after") or "").strip()
                wait_s = 0.0
                try:
                    wait_s = float(retry_after) if retry_after else 0.0
                except ValueError:
                    wait_s = 0.0
                if wait_s <= 0:
                    wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                llm_console.log_end(
                    req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=f"http_status_{resp.status_code}"
                )
                await asyncio.sleep(wait_s)
                continue

            resp.raise_for_status()
            data = resp.json()
            try:
                content = str(data["choices"][0]["message"]["content"] or "")
                finish_reason = ""
                usage: Dict[str, Any] = {}
                try:
                    choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                    finish_reason = str(choice0.get("finish_reason") or "")
                except Exception:
                    finish_reason = ""
                if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                    usage = dict(data.get("usage") or {})
                if content:
                    llm_console.log_delta(req_id=req_id, channel="content", text=content)
                llm_console.log_end(
                    req_id=req_id,
                    elapsed_s=_elapsed_s(start_ts),
                    finish_reason=finish_reason,
                    usage=usage,
                    content_chars=len(content),
                )
                return content
            except Exception:
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error="invalid_response")
                return ""
        except Exception as exc:
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=str(exc))
            if attempt < 2:
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            return ""

    return ""


def pick_questions(questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
    scored = []
    for q in questions:
        stem = str(q.get("stem") or "")
        if not stem or len(stem) < 8:
            continue
        penalty = stem.count("[图片:") * 50 + max(0, len(stem) - 500) // 20
        scored.append((penalty, q))
    scored.sort(key=lambda x: x[0])
    return [q for _, q in scored[: max(1, limit)]]
