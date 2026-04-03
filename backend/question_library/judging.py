from __future__ import annotations

import json
import os
from typing import Any

from backend.core.settings import LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.llm.client import is_llm_configured
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import get_subject_bank, infer_subject_family


def _resolve_judge_model() -> str:
    raw = str(os.getenv("QUESTION_LIBRARY_JUDGE_MODEL") or "").strip()
    if raw:
        return raw
    return str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"


async def solve_draft(
    stem: str,
    options: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"match": False, "final_answer": "", "issues": ["llm_not_configured"], "summary": ""}

    subject = str((options or {}).get("subject") or "").strip()
    proposed_answer = str((options or {}).get("proposed_answer") or "").strip()
    family = infer_subject_family(subject)
    bank = get_subject_bank(subject)

    # Two-phase prompt: solve independently FIRST, then compare with proposed answer.
    # This avoids anchoring bias where the model confirms an incorrect proposed answer.
    payload = {
        "subject": subject,
        "stem": str(stem or "").strip(),
        "task": "请你先完整地独立解题，写出详细推导过程和最终答案。解题完成后，再与下方的【参考答案】进行对比，判断参考答案是否正确。",
        "proposed_answer": proposed_answer,
        "output_schema": {
            "solving_steps": "string (你的完整解题过程，包含关键推导步骤)",
            "final_answer": "string (你独立求解得到的最终答案，LaTeX)",
            "match": "bool (你的答案与参考答案的结论是否一致)",
            "issues": "string[] (参考答案中的错误/不一致之处，没有则为空数组)",
            "summary": "string (简要总结)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    f"<role>{str(bank.system_role or '').strip() or '你是严谨的解题专家'}（独立解题，不受参考答案影响）。</role>\n"
                    "<task>\n"
                    "  <phase id='1'>完全忽略参考答案，独立完整解题，写出关键推导步骤和最终答案。</phase>\n"
                    "  <phase id='2'>将你的答案与参考答案对比，判断结论是否等价。</phase>\n"
                    "</task>\n"
                    f"<subject_family>{family}</subject_family>\n"
                    "<subject_rules>\n"
                    "  <physics>物理题：先过程建模/受力分析，再列式求解；注意方向与单位量纲。</physics>\n"
                    "  <chemistry>化学题：方程式配平与守恒优先；状态条件完整。</chemistry>\n"
                    "  <chinese>语文题：答案需紧扣文本证据与设问要求，表述规范。</chinese>\n"
                    "  <english>英语题：先定位依据，再给出规范答案；语法与语篇一致。</english>\n"
                    "</subject_rules>\n"
                    "<match_criteria>\n"
                    "  结论等价（如 x=2 与 \\(x=2\\) 视为相同形式）则 match=true。\n"
                    "  若不一致，先检查自己的解法是否有误，再做最终判断。\n"
                    "</match_criteria>\n"
                    "<output_format>严格输出 JSON object，不输出 Markdown 或额外解释。</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model() or "openai/gpt-5.4-mini",
        temperature=0.15,
        max_tokens=0,
        req_id_prefix="ql_solver",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="判题筛选",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    match = bool(obj.get("match"))
    issues = obj.get("issues")
    return {
        "match": match,
        "final_answer": str(obj.get("final_answer") or "").strip(),
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
    }


async def check_ambiguity(
    draft: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"ambiguous": True, "issues": ["llm_not_configured"], "summary": ""}

    payload = {
        "stem": str((draft or {}).get("stem") or "").strip(),
        "answer": str((draft or {}).get("answer") or "").strip(),
        "output_schema": {
            "ambiguous": "bool (是否存在合理歧义/多解导致答案不唯一)",
            "issues": "string[]",
            "summary": "string",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    "<role>你是专业审题专家，专门识别导致答案不唯一的歧义问题。</role>\n"
                    "<ambiguity_criteria>\n"
                    "  <rule>仅当题干条件允许多种合理解读且导致不同结论时，判定 ambiguous=true。</rule>\n"
                    "  <not_ambiguous>分类讨论本身不是歧义</not_ambiguous>\n"
                    "  <not_ambiguous>参数范围讨论不是歧义</not_ambiguous>\n"
                    "  <is_ambiguous>无法从题干确定唯一答案路径时才标记 ambiguous=true</is_ambiguous>\n"
                    "</ambiguity_criteria>\n"
                    "<output_format>严格输出 JSON object。</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_amb",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="判题筛选",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    return {
        "ambiguous": bool(obj.get("ambiguous")),
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
    }


async def judge_draft(
    draft: dict,
    spec: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return {"pass": False, "overall_score": 0, "issues": ["llm_not_configured"], "summary": ""}

    subject = str((spec or {}).get("subject") or "").strip()
    difficulty = str((spec or {}).get("difficulty") or "").strip()
    family = infer_subject_family(subject)
    bank = get_subject_bank(subject)
    requirements = (
        f"目标难度：{difficulty or '中等偏难'}。必须有新意与区分度，且符合 spec 的推理结构："
        f"{str((spec or {}).get('reasoning') or '').strip()}。"
    )

    extra_dims = []
    extra_dim_tags = ""
    if family == "physics":
        extra_dims = [{"name": "物理过程分析", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='物理过程分析'>过程建模/受力分析/量纲单位是否正确，物理意义是否自洽</dim>\n"
    elif family == "chemistry":
        extra_dims = [{"name": "化学原理正确性", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='化学原理正确性'>原理正确、配平规范、状态条件完整，守恒关系正确</dim>\n"
    elif family == "biology":
        extra_dims = [{"name": "证据链与实验设计", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='证据链与实验设计'>推断是否基于材料证据；实验题是否体现对照与变量控制</dim>\n"
    elif family == "chinese":
        extra_dims = [{"name": "文本证据与表述", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='文本证据与表述'>答案是否引用/依托文本证据，表述是否规范、分点清晰</dim>\n"
    elif family == "english":
        extra_dims = [{"name": "语篇依据与语言准确", "score": "int 1-10", "comment": "string"}]
        extra_dim_tags = "  <dim name='语篇依据与语言准确'>定位依据是否充分；语法/表达是否准确规范</dim>\n"

    payload = {
        "subject": subject,
        "requirements": requirements,
        "spec": {
            "skill": str((spec or {}).get("skill") or "").strip(),
            "reasoning": str((spec or {}).get("reasoning") or "").strip(),
            "trap": str((spec or {}).get("trap") or "").strip(),
            "surface": str((spec or {}).get("surface") or "").strip(),
        },
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip()[:1600],
            "answer": str((draft or {}).get("answer") or "").strip()[:1200],
            "analysis": str((draft or {}).get("analysis") or "").strip()[:2000],
        },
        "output_schema": {
            "verdict": "string (好题|普通题|差题)",
            "overall_score": "int 0-100",
            "dimensions": [
                {"name": "思维含量", "score": "int 1-10", "comment": "string"},
                {"name": "区分度", "score": "int 1-10", "comment": "string"},
                {"name": "知识覆盖", "score": "int 1-10", "comment": "string"},
                {"name": "表述规范", "score": "int 1-10", "comment": "string"},
                {"name": "创新性", "score": "int 1-10", "comment": "string"},
                {"name": "答案解析自洽", "score": "int 1-10", "comment": "string"},
                *extra_dims,
            ],
            "highlights": "string[]",
            "issues": "string[]",
            "summary": "string",
            "difficulty_estimate": "string (简单|中等|偏难|困难)",
            "novelty_score": "int 1-10",
            "reasoning_depth": "int 1-10",
            "pass": "bool",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    f"<role>{str(bank.system_role or '').strip() or '你是资深高中教研员'}，按高考评审标准鉴别试题质量，评分客观准确。</role>\n"
                    "<scoring_dimensions>\n"
                    "  <dim name='思维含量'>是否需要多步推理或策略选择，非机械套公式</dim>\n"
                    "  <dim name='区分度'>能否区分不同层次学生，非教材例题换皮</dim>\n"
                    "  <dim name='知识覆盖'>核心概念运用深度，考查角度是否有价值</dim>\n"
                    "  <dim name='表述规范'>题干清晰，LaTeX正确，条件充分无歧义</dim>\n"
                    "  <dim name='创新性'>非教材直接例题，有新约束条件或概念组合</dim>\n"
                    "  <dim name='答案解析自洽'>推导每步正确，结论与答案字段完全一致</dim>\n"
                    f"{extra_dim_tags}"
                    "</scoring_dimensions>\n"
                    "<pass_criteria>overall_score≥70 且 答案解析自洽≥7 且 思维含量≥6</pass_criteria>\n"
                    "<output_format>严格输出 JSON object，不要输出Markdown或解释。</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_judge",
        retries=3,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="判题筛选",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    dims = obj.get("dimensions")
    return {
        "pass": bool(obj.get("pass")),
        "verdict": str(obj.get("verdict") or "").strip(),
        "overall_score": int(obj.get("overall_score") or 0),
        "dimensions": list(dims or []) if isinstance(dims, list) else [],
        "highlights": list(obj.get("highlights") or []) if isinstance(obj.get("highlights"), list) else [],
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
        "difficulty_estimate": str(obj.get("difficulty_estimate") or "").strip(),
        "novelty_score": int(obj.get("novelty_score") or 0),
        "reasoning_depth": int(obj.get("reasoning_depth") or 0),
    }


async def refine_draft(
    draft: dict,
    judge: dict,
    *,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    if not is_llm_configured():
        return dict(draft or {})

    issues = judge.get("issues") if isinstance(judge, dict) else []
    payload = {
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip(),
            "answer": str((draft or {}).get("answer") or "").strip(),
            "analysis": str((draft or {}).get("analysis") or "").strip(),
        },
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "output_schema": {"stem": "string", "answer": "string", "analysis": "string"},
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    "<role>你是教研员修题助手，负责根据 issues 最小化修改题目。</role>\n"
                    "<edit_principle>优先只改有问题的部分，保持难度、知识点和题型不变。</edit_principle>\n"
                    "<latex_rules>行内公式：\\(...\\)　独立公式：\\[...\\]　严禁 $...$</latex_rules>\n"
                    "<verification>修改后验算答案正确性，确保 stem/answer/analysis 三者完全自洽。</verification>\n"
                    "<output_format>严格输出 JSON object。</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.25,
        max_tokens=0,
        req_id_prefix="ql_repair",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="判题筛选",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    out = dict(draft or {})
    out["stem"] = str(obj.get("stem") or out.get("stem") or "").strip()
    out["answer"] = str(obj.get("answer") or out.get("answer") or "").strip()
    out["analysis"] = str(obj.get("analysis") or out.get("analysis") or "").strip()
    return out


def _judge_payload_preview(draft: dict) -> dict:
    if not isinstance(draft, dict):
        return {}
    return {
        "stem": _clip(str(draft.get("stem") or "").strip(), 320),
        "answer": _clip(str(draft.get("answer") or "").strip(), 180),
        "analysis": _clip(str(draft.get("analysis") or "").strip(), 240),
    }


def _normalize_judge_output(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    out = dict(value)
    out["issues"] = list(out.get("issues") or []) if isinstance(out.get("issues"), list) else []
    return out
