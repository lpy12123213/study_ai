from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.llm.client import chat_completion_text


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
    return await chat_completion_text(
        messages=messages,
        model=str(model or "").strip(),
        temperature=float(temperature),
        max_tokens=int(max_tokens or 0),
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="mcp-stdio",
    )


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
