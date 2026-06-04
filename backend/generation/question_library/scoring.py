from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.database.repositories.question.question_library import set_hidden, upsert_question_library_items
from backend.llm.runner import run_json
from backend.shared.question_thinking import (
    extract_thinking_depth,
    merge_method_context,
    replace_thinking_depth_dimension,
)


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value or [], ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "").strip()
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp_int(value: Any, *, default: int, min_v: int, max_v: int) -> int:
    n = _as_int(value, default)
    return max(min_v, min(max_v, n))


def _normalize_questions(questions: List[dict]) -> List[dict]:
    out: List[dict] = []
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        stem = str(item.get("stem") or "").strip()
        if not qid or not stem:
            continue
        out.append(
            {
                "question_id": qid,
                "stem": _clip(stem, 1400),
                "question_type": str(item.get("question_type") or "").strip(),
                "difficulty": str(item.get("difficulty") or "").strip(),
                "knowledge_point": str(item.get("knowledge_point") or "").strip(),
                "answer": _clip(str(item.get("answer") or ""), 500),
                "analysis": _clip(str(item.get("analysis") or ""), 800),
            }
        )
    return out[:50]


def _normalize_method_summary(value: Any) -> List[dict]:
    raw = value if isinstance(value, list) else []
    out: List[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        family = str(item.get("method_family") or item.get("family") or item.get("name") or "").strip()
        if not family:
            continue
        examples = item.get("example_question_ids") if isinstance(item.get("example_question_ids"), list) else []
        out.append(
            {
                "method_family": family,
                "count": max(1, _as_int(item.get("count"), 1)),
                "method_signature": str(item.get("method_signature") or item.get("signature") or "").strip(),
                "method_rarity": str(item.get("method_rarity") or item.get("rarity") or "").strip(),
                "example_question_ids": [str(x or "").strip() for x in examples if str(x or "").strip()][:5],
            }
        )
    return out


def _normalize_scored_item(raw: dict, *, fallback_qid: str) -> dict:
    qid = str(raw.get("question_id") or fallback_qid or "").strip()
    base_dimensions = raw.get("dimensions") if isinstance(raw.get("dimensions"), list) else []
    existing_depth = extract_thinking_depth(base_dimensions)

    thinking_score = raw.get("thinking_depth_score")
    if thinking_score is None:
        thinking_score = existing_depth.get("score")
    method_family = str(raw.get("method_family") or existing_depth.get("method_family") or "").strip()
    method_signature = str(raw.get("method_signature") or existing_depth.get("method_signature") or "").strip()
    method_rarity = str(raw.get("method_rarity") or existing_depth.get("method_rarity") or "").strip()
    similar_count = raw.get("similar_method_count")
    if similar_count is None:
        similar_count = existing_depth.get("similar_method_count")
    depth_comment = str(
        raw.get("thinking_depth_comment")
        or raw.get("comment")
        or existing_depth.get("comment")
        or raw.get("summary")
        or ""
    ).strip()

    dimensions = replace_thinking_depth_dimension(
        base_dimensions,
        {
            "score": _clamp_int(thinking_score, default=1, min_v=1, max_v=10),
            "comment": depth_comment,
            "method_family": method_family,
            "method_signature": method_signature,
            "method_rarity": method_rarity,
            "similar_method_count": max(0, _as_int(similar_count, 0)),
        },
    )
    depth = extract_thinking_depth(dimensions)

    return {
        "question_id": qid,
        "verdict": str(raw.get("verdict") or "").strip(),
        "overall_score": _clamp_int(raw.get("overall_score"), default=0, min_v=0, max_v=100),
        "dimensions": dimensions,
        "highlights": list(raw.get("highlights") or []) if isinstance(raw.get("highlights"), list) else [],
        "issues": list(raw.get("issues") or []) if isinstance(raw.get("issues"), list) else [],
        "summary": str(raw.get("summary") or depth.get("comment") or "").strip(),
        "thinking_depth_score": depth.get("score"),
        "method_family": depth.get("method_family") or method_family,
        "method_signature": depth.get("method_signature") or method_signature,
        "method_rarity": depth.get("method_rarity") or method_rarity,
        "similar_method_count": depth.get("similar_method_count"),
    }


async def score_question_batch_with_thinking_depth(
    *,
    subject: str,
    questions: List[dict],
    model: str,
    method_context: List[dict] | None = None,
    requirements: str = "",
) -> dict:
    qlist = _normalize_questions(questions)
    if not qlist:
        return {"items": [], "method_summary": []}

    context = merge_method_context(method_context or [], [], max_families=80)
    payload = {
        "subject": subject,
        "requirements": (requirements or "").strip(),
        "batch_size": len(qlist),
        "questions": qlist,
        "prior_method_context": context,
        "thinking_depth_definition": (
            "思维深度是解题方法的稀有度与思维含金量，不等同于计算量、题干长度或表面难度。"
            "常规套公式/直接代入应低分；需要罕见转化、辅助构造、反常规视角、隐含模型识别、"
            "多对象联动或高质量分类讨论的题应高分。"
        ),
        "scoring_scale": {
            "1-3": "常规套路、模板代入、同源题很多",
            "4-6": "有一定转化或组合，但方法仍常见",
            "7-8": "方法较少见，需要明确的构造/转化/洞察",
            "9-10": "方法小众且高含金量，显著依赖稀有思路或关键一招",
        },
        "output_schema": {
            "items": [
                {
                    "question_id": "string",
                    "verdict": "string (好题|普通题|差题)",
                    "overall_score": "int 0-100",
                    "thinking_depth_score": "int 1-10",
                    "method_family": "string, compact same-method family name",
                    "method_signature": "string, one-sentence method signature",
                    "method_rarity": "string (common|uncommon|rare)",
                    "similar_method_count": "int, including prior_method_context and this batch",
                    "summary": "string",
                    "dimensions": [{"name": "string", "score": "int 1-10", "comment": "string"}],
                    "highlights": "string[]",
                    "issues": "string[]",
                }
            ],
            "method_summary": [
                {
                    "method_family": "string",
                    "count": "int, same-method count in this batch",
                    "method_signature": "string",
                    "method_rarity": "string",
                    "example_question_ids": "string[]",
                }
            ],
        },
    }
    obj = await run_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "<role>You are a senior high-school curriculum researcher. Score a batch of questions by comparing "
                    "their solution-method rarity and intellectual depth.</role>\n"
                    "<batch_policy>Process up to 50 questions together. First identify the core solving method of each "
                    "question, group same-origin methods, compare against prior_method_context, then score each "
                    "question's thinking_depth_score from 1 to 10.</batch_policy>\n"
                    "<carryover>Use prior_method_context as compact memory from earlier batches. Return method_summary so "
                    "the caller can carry method-family counts into the next batch.</carryover>\n"
                    "<avoid>Do not reward long wording, tedious calculation, or ordinary difficulty alone.</avoid>\n"
                    "<output_format>Output a strict JSON object only.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=model,
        temperature=0.15,
        max_tokens=4200,
        response_format={"type": "json_object"},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_thinking_depth_score",
    )
    obj = obj if isinstance(obj, dict) else {}
    raw_items = obj.get("items") or obj.get("scores") or []
    raw_items = raw_items if isinstance(raw_items, list) else []
    by_qid: Dict[str, dict] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = _normalize_scored_item(raw, fallback_qid="")
        qid = str(item.get("question_id") or "").strip()
        if qid:
            by_qid[qid] = item

    items: List[dict] = []
    for q in qlist:
        qid = str(q.get("question_id") or "").strip()
        if qid in by_qid:
            items.append(by_qid[qid])
        else:
            items.append(
                _normalize_scored_item(
                    {
                        "question_id": qid,
                        "verdict": "普通题",
                        "overall_score": 0,
                        "thinking_depth_score": 1,
                        "method_family": "未识别",
                        "method_rarity": "common",
                        "similar_method_count": 0,
                        "summary": "模型未返回该题评分",
                    },
                    fallback_qid=qid,
                )
            )

    return {"items": items, "method_summary": _normalize_method_summary(obj.get("method_summary"))}


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
    obj = await run_json(
        messages=[
            {"role": "system", "content": (
                "<role>You are a senior high-school curriculum researcher. Evaluate question quality by college-entrance-exam standards and score objectively.</role>\n"
                "<scoring_principle>只看题目实际质量，不受题目长短影响。</scoring_principle>\n"
                "<extra_requirement>If the requirements field is non-empty, prioritize evaluation according to those requirements.</extra_requirement>\n"
                "<output_format>Output a strict JSON object only.</output_format>"
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
    obj = obj if isinstance(obj, dict) else {}
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
