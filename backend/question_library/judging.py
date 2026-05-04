from __future__ import annotations

import json
import os
from typing import Any

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.agentic.prompts import create_default_prompt_registry
from backend.llm.client import is_llm_configured
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import get_subject_bank, infer_subject_family


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


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
        "task": "First solve the problem completely and independently, including detailed derivation and the final answer. After solving, compare your result with the reference answer below and judge whether the reference answer is correct.",
        "proposed_answer": proposed_answer,
        "output_schema": {
            "solving_steps": "string (your complete solving process, including key derivation steps)",
            "final_answer": "string (the final answer you independently derived, in LaTeX)",
            "match": "bool (whether your answer is conclusion-equivalent to the reference answer)",
            "issues": "string[] (errors or inconsistencies in the reference answer; empty array if none)",
            "summary": "string (brief summary)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.solve.independent.v1")
                    + "\n\n"
                    f"<role>{str(bank.system_role or '').strip() or 'You are a rigorous problem-solving expert'}. Solve independently and do not be influenced by the reference answer.</role>\n"
                    "<task>\n"
                    "  <phase id='1'>Completely ignore the reference answer. Solve independently and write key derivation steps and the final answer.</phase>\n"
                    "  <phase id='2'>Compare your answer with the reference answer and judge whether the conclusions are equivalent.</phase>\n"
                    "</task>\n"
                    f"<subject_family>{family}</subject_family>\n"
                    "<subject_rules>\n"
                    "  <physics>Physics: model the process/analyze forces before setting equations; check directions, units, and dimensions.</physics>\n"
                    "  <chemistry>Chemistry: prioritize balanced equations and conservation; keep states and conditions complete.</chemistry>\n"
                    "  <chinese>Chinese: answers must closely follow textual evidence and question requirements with standard wording.</chinese>\n"
                    "  <english>English: locate evidence first, then provide a standard answer; grammar and discourse must be consistent.</english>\n"
                    "</subject_rules>\n"
                    "<match_criteria>\n"
                    "  If conclusions are equivalent, such as x=2 and \\(x=2\\), set match=true.\n"
                    "  If inconsistent, first check whether your own solution is wrong before making the final judgment.\n"
                    "</match_criteria>\n"
                    "<output_format>Output a strict JSON object only. Do not output Markdown or extra explanation.</output_format>"
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
                    _prompt("question.judge.ambiguity.v1")
                    + "\n\n"
                    "<role>You are a professional question-review expert specializing in ambiguity that may cause non-unique answers.</role>\n"
                    "<ambiguity_criteria>\n"
                    "  <rule>Set ambiguous=true only when the stem allows multiple reasonable interpretations that lead to different conclusions.</rule>\n"
                    "  <not_ambiguous>Case analysis itself is not ambiguity.</not_ambiguous>\n"
                    "  <not_ambiguous>Parameter-range discussion is not ambiguity.</not_ambiguous>\n"
                    "  <is_ambiguous>Mark ambiguous=true only when the stem cannot determine a unique answer path.</is_ambiguous>\n"
                    "</ambiguity_criteria>\n"
                    "<output_format>Output a strict JSON object only.</output_format>"
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
        f"Target difficulty: {difficulty or 'medium-hard'}. The question must be novel, discriminative, and follow the reasoning structure in spec: "
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
                    _prompt("question.judge.quality.v1")
                    + "\n\n"
                    f"<role>{str(bank.system_role or '').strip() or 'You are a senior high-school curriculum researcher'}. Evaluate question quality by college-entrance-exam review standards and score objectively.</role>\n"
                    "<scoring_dimensions>\n"
                    "  <dim name='reasoning_depth'>Requires multi-step reasoning or strategic choices, not mechanical formula substitution.</dim>\n"
                    "  <dim name='discrimination'>Distinguishes students at different levels and is not a disguised textbook example.</dim>\n"
                    "  <dim name='knowledge_coverage'>Uses core concepts deeply and has a valuable assessment angle.</dim>\n"
                    "  <dim name='wording_standard'>The stem is clear, LaTeX is correct, and conditions are sufficient and unambiguous.</dim>\n"
                    "  <dim name='novelty'>Not a direct textbook example; includes new constraints or concept combinations.</dim>\n"
                    "  <dim name='answer_analysis_consistency'>Every derivation step is correct and the conclusion exactly matches the answer field.</dim>\n"
                    f"{extra_dim_tags}"
                    "</scoring_dimensions>\n"
                    "<pass_criteria>overall_score >= 70, answer_analysis_consistency >= 7, and reasoning_depth >= 6.</pass_criteria>\n"
                    "<output_format>Output a strict JSON object only. Do not output Markdown or explanations.</output_format>"
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
                    _prompt("question.repair.minimal.v1")
                    + "\n\n"
                    "<role>You are a curriculum question-repair assistant responsible for minimally modifying a question according to issues.</role>\n"
                    "<edit_principle>Prefer changing only problematic parts while preserving difficulty, knowledge point, and question type.</edit_principle>\n"
                    "<latex_rules>Inline formulas: \\(...\\). Display formulas: \\[...\\]. Do not use $...$.</latex_rules>\n"
                    "<verification>After modification, verify answer correctness and ensure stem/answer/analysis are fully self-consistent.</verification>\n"
                    "<output_format>Output a strict JSON object only.</output_format>"
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
