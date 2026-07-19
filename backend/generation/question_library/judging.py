from __future__ import annotations

import json
import os
from typing import Any

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.curriculum_context import curriculum_context_for_prompt
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.intuition_practice import normalize_intuition_packet
from backend.generation.question_library.subject_knowledge import get_subject_bank, infer_subject_family
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _resolve_judge_model() -> str:
    raw = str(os.getenv("QUESTION_LIBRARY_JUDGE_MODEL") or "").strip()
    if raw:
        return raw
    return str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


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
        stage_label="快速校验",
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
        stage_label="快速校验",
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


async def quick_validate_draft(
    draft: dict,
    spec: dict,
    *,
    source_pack: dict | None = None,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    """Run the minimum safety gate required for a student self-practice packet.

    This deliberately avoids competition-style quality scoring, repeated solver
    consensus, and psychometric claims.  One review call checks only curriculum
    scope, correctness/answer consistency, and whether the task is sufficiently
    specified and unambiguous.
    """

    if not is_llm_configured():
        return {
            "pass": False,
            "scope_ok": False,
            "answer_correct": False,
            "answer_analysis_consistent": False,
            "conditions_sufficient": False,
            "unambiguous": False,
            "transfer_valid": False,
            "issues": ["llm_not_configured"],
            "summary": "",
        }

    subject = str((spec or {}).get("subject") or (source_pack or {}).get("subject") or "").strip()
    curriculum = curriculum_context_for_prompt(source_pack or {})
    payload = {
        "subject": subject,
        "curriculum_context": curriculum,
        "question": {
            "stem": str((draft or {}).get("stem") or "").strip()[:2400],
            "answer": str((draft or {}).get("answer") or "").strip()[:2000],
            "analysis": str((draft or {}).get("analysis") or "").strip()[:3200],
            "intuition_packet": (draft or {}).get("intuition_packet")
            if isinstance((draft or {}).get("intuition_packet"), dict)
            else {},
        },
        "output_schema": {
            "scope_ok": "bool (all required knowledge and methods are in curriculum scope)",
            "answer_correct": "bool (independently checking the task leads to the proposed answer)",
            "answer_analysis_consistent": "bool",
            "conditions_sufficient": "bool",
            "unambiguous": "bool",
            "transfer_valid": "bool (the transfer stage preserves the decisive structure while changing at least two surface features, not only numbers)",
            "issues": "string[] (short, actionable issue codes or descriptions)",
            "summary": "string",
            "pass": "bool (true only when all five checks above pass)",
        },
    }
    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.judge.quality.v1")
                    + "\n\n"
                    "<role>You are a lightweight self-practice question checker.</role>\n"
                    "<scope>Check only: curriculum boundary, answer correctness and answer-analysis consistency, sufficient conditions, fatal ambiguity, and whether transfer preserves the decisive structure while changing at least two surface features.</scope>\n"
                    "<independent_check>Briefly solve or verify each stage before comparing with the proposed answer. Use the scientific-compute tool only when it materially helps.</independent_check>\n"
                    "<not_required>Do not score novelty, competition difficulty, discrimination, elegance, or psychometrics. A short low-entry task may pass.</not_required>\n"
                    "<ambiguity>Case discussion and open reflection are not ambiguity when the allowed response space and reference criteria are clear.</ambiguity>\n"
                    "<pass_rule>pass=true only if scope_ok, answer_correct, answer_analysis_consistent, conditions_sufficient, unambiguous, and transfer_valid are all true.</pass_rule>\n"
                    "<output_format>Output one strict JSON object only.</output_format>"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_resolve_judge_model(),
        temperature=0.1,
        max_tokens=0,
        req_id_prefix="ql_judge",
        retries=2,
        raise_on_fail=False,
        stage_id="judge",
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    legacy_pass = bool(obj.get("pass"))

    def _flag(name: str) -> bool:
        return bool(obj.get(name)) if name in obj else legacy_pass

    flags = {
        "scope_ok": _flag("scope_ok"),
        "answer_correct": _flag("answer_correct"),
        "answer_analysis_consistent": _flag("answer_analysis_consistent"),
        "conditions_sufficient": _flag("conditions_sufficient"),
        "unambiguous": _flag("unambiguous"),
        "transfer_valid": _flag("transfer_valid"),
    }
    issues = [str(item or "").strip() for item in (obj.get("issues") or []) if str(item or "").strip()]
    issue_by_flag = {
        "scope_ok": "out_of_scope",
        "answer_correct": "answer_incorrect",
        "answer_analysis_consistent": "answer_analysis_mismatch",
        "conditions_sufficient": "conditions_insufficient",
        "unambiguous": "fatal_ambiguity",
        "transfer_valid": "transfer_invalid",
    }
    for name, ok in flags.items():
        if not ok and issue_by_flag[name] not in issues:
            issues.append(issue_by_flag[name])
    passed = all(flags.values())
    return {
        "pass": passed,
        **flags,
        "issues": issues[:12],
        "summary": str(obj.get("summary") or "").strip(),
        "overall_score": 100 if passed else 0,
    }


async def judge_draft(
    draft: dict,
    spec: dict,
    *,
    source_pack: dict | None = None,
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
    curriculum = curriculum_context_for_prompt(source_pack or {})
    curriculum_requirements = [str(x or "").strip() for x in (curriculum.get("question_requirements") or []) if str(x or "").strip()]
    if curriculum_requirements:
        requirements += " 新课标出题要求：" + "；".join(curriculum_requirements[:8]) + "。"
    in_scope = list((curriculum.get("knowledge_scope") or {}).get("in_scope") or [])
    out_of_scope = list((curriculum.get("knowledge_scope") or {}).get("out_of_scope") or [])
    if in_scope:
        requirements += " 知识范围应覆盖：" + "、".join(in_scope[:8]) + "。"
    if out_of_scope:
        requirements += " 不得涉及：" + "、".join(out_of_scope[:6]) + "。"
    prerequisites = [str(x or "").strip() for x in (curriculum.get("prerequisites") or []) if str(x or "").strip()]
    if prerequisites:
        requirements += " 前置知识假定：" + "、".join(prerequisites[:8]) + "。"

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
        "curriculum_context": curriculum,
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
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    dims = obj.get("dimensions")
    return {
        "pass": bool(obj.get("pass")),
        "verdict": str(obj.get("verdict") or "").strip(),
        "overall_score": _coerce_int(obj.get("overall_score"), 0),
        "dimensions": list(dims or []) if isinstance(dims, list) else [],
        "highlights": list(obj.get("highlights") or []) if isinstance(obj.get("highlights"), list) else [],
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
        "difficulty_estimate": str(obj.get("difficulty_estimate") or "").strip(),
        "novelty_score": _coerce_int(obj.get("novelty_score"), 0),
        "reasoning_depth": _coerce_int(obj.get("reasoning_depth"), 0),
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
            "intuition_packet": (draft or {}).get("intuition_packet")
            if isinstance((draft or {}).get("intuition_packet"), dict)
            else {},
        },
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "output_schema": {
            "stem": "string",
            "answer": "string",
            "analysis": "string",
            "intuition_packet": "object (same version 1.0 packet contract, repaired consistently)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    _prompt("question.repair.minimal.v1")
                    + "\n\n"
                    "<role>You are a curriculum question-repair assistant responsible for minimally modifying a question according to issues.</role>\n"
                    "<edit_principle>Prefer changing only problematic parts while preserving difficulty, knowledge point, question type, intuition atom, and practice-stage order.</edit_principle>\n"
                    "<packet_integrity>Repair stem, answer, analysis, and intuition_packet together. The required perception/model_externalization/transfer stages must remain mutually consistent.</packet_integrity>\n"
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
        stage_label="快速校验",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )
    obj = _extract_json_obj(text)
    out = dict(draft or {})
    out["stem"] = str(obj.get("stem") or out.get("stem") or "").strip()
    out["answer"] = str(obj.get("answer") or out.get("answer") or "").strip()
    out["analysis"] = str(obj.get("analysis") or out.get("analysis") or "").strip()
    existing_packet = out.get("intuition_packet") if isinstance(out.get("intuition_packet"), dict) else {}
    out["intuition_packet"] = normalize_intuition_packet(
        obj.get("intuition_packet") if isinstance(obj.get("intuition_packet"), dict) else existing_packet,
        practice_config=existing_packet,
        atom=existing_packet.get("atom") if isinstance(existing_packet.get("atom"), dict) else {},
        legacy_question=out,
    )
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
