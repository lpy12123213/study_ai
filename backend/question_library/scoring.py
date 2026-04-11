from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from backend.llm.client import chat_completion_text
from backend.database.repositories.question.question_library import set_hidden, upsert_question_library_items


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value or [], ensure_ascii=False)
    except Exception:
        return "[]"


def _extract_json_obj(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\\s*", "", raw).lstrip()
        raw = re.sub(r"\\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def score_stem_with_llm(*, subject: str, stem: str, model: str, requirements: str = "") -> dict:
    payload = {
        "subject": subject,
        "requirements": (requirements or "").strip(),
        "question": {"stem": (stem or "").strip()[:1500]},
        "output_schema": {
            "verdict": "string (好题|普通题|差题)",
            "overall_score": "int 0-100",
            "dimensions": [{"name": "string", "score": "int 1-10", "comment": "string"}],
            "highlights": "string[]",
            "issues": "string[]",
            "summary": "string",
        },
    }
    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": (
                "<role>你是资深高中教研员，按高考标准鉴别试题质量，评分客观准确。</role>\n"
                "<scoring_principle>只看题目实际质量，不受题目长短影响。</scoring_principle>\n"
                "<extra_requirement>若 requirements 字段有内容，按其中要求重点评价。</extra_requirement>\n"
                "<output_format>严格输出 JSON object。</output_format>"
            )},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=model,
        temperature=0.2,
        max_tokens=1800,
        response_format={"type": "json_object"},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_score",
    )
    obj = _extract_json_obj(text)
    return {
        "verdict": str(obj.get("verdict") or "").strip(),
        "overall_score": int(obj.get("overall_score") or 0),
        "dimensions": list(obj.get("dimensions") or []),
        "highlights": list(obj.get("highlights") or []),
        "issues": list(obj.get("issues") or []),
        "summary": str(obj.get("summary") or "").strip(),
    }


async def apply_score_and_hide(
    *,
    user_id: str,
    question_id: str,
    overall_score: int,
    verdict: str,
    dimensions: List[Dict[str, Any]],
    summary: str,
    threshold: int,
) -> None:
    await upsert_question_library_items(
        user_id=user_id,
        items=[
            {
                "question_id": question_id,
                "ai_score": int(overall_score),
                "ai_verdict": str(verdict or "").strip(),
                "ai_dimensions_json": _to_json_str(dimensions),
                "ai_summary": str(summary or "").strip(),
            }
        ],
    )
    if int(overall_score) < int(threshold):
        await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
