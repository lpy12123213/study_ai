from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.curriculum_context import curriculum_context_for_prompt
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.intuition_practice import (
    normalize_intuition_atom,
    normalize_intuition_practice_config,
)
from backend.generation.question_library.subject_knowledge import get_subject_bank, infer_subject_family
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _prompt(prompt_id: str) -> str:
    return create_default_prompt_registry().render(prompt_id).content


def _normalize_seed(item: Any) -> Optional[dict]:
    if not isinstance(item, dict):
        return None

    concept = str(item.get("concept") or item.get("idea") or "").strip()
    angle = str(item.get("angle") or item.get("reasoning_angle") or item.get("twist") or "").strip()
    scenario = str(item.get("scenario") or item.get("context") or "").strip()
    seed_tag = str(item.get("seed_tag") or item.get("seedTag") or item.get("tag") or "").strip()
    skill_hint = str(item.get("skill_hint") or item.get("skillHint") or item.get("skill") or "").strip()
    reasoning_hint = str(item.get("reasoning_hint") or item.get("reasoningHint") or item.get("reasoning") or "").strip()
    novelty_note = str(item.get("novelty_note") or item.get("novelty") or item.get("note") or "").strip()
    mother_question_demand = str(
        item.get("mother_question_demand")
        or item.get("motherQuestionDemand")
        or item.get("core_question_demand")
        or ""
    ).strip()
    topic_binding = str(item.get("topic_binding") or item.get("topicBinding") or "").strip()

    atom = normalize_intuition_atom(
        item.get("intuition_atom"),
        topic=concept,
        seed_tag=seed_tag or angle,
    )

    if not any([concept, angle, scenario, seed_tag, skill_hint, reasoning_hint]):
        return None

    if not seed_tag:
        seed_tag = concept or angle or "创意种子"

    return {
        "concept": _clip(concept, 120),
        "angle": _clip(angle, 140),
        "scenario": _clip(scenario, 160),
        "seed_tag": _clip(seed_tag, 60),
        "skill_hint": _clip(skill_hint, 80),
        "reasoning_hint": _clip(reasoning_hint, 120),
        "novelty_note": _clip(novelty_note, 180),
        "mother_question_demand": _clip(mother_question_demand, 180),
        "topic_binding": _clip(topic_binding, 180),
        "intuition_atom": atom,
    }


async def brainstorm_creative_seeds(
    source_pack: dict,
    *,
    seed_count: int = 8,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> List[dict]:
    """Brainstorm intuition atoms before beam-search spec expansion.

    Output: list of seeds with keys:
    - concept/angle/scenario/seed_tag/skill_hint/reasoning_hint/novelty_note
    """

    if not is_llm_configured():
        return []

    sp = source_pack if isinstance(source_pack, dict) else {}
    subject = str(sp.get("subject") or "").strip() or "高中数学"
    topic = str(sp.get("requested_topic") or sp.get("topic") or "").strip()
    family = infer_subject_family(subject)
    bank = get_subject_bank(subject)

    seed_count = max(4, min(int(seed_count or 6), 8))
    practice_config = normalize_intuition_practice_config(sp.get("intuition_practice"))

    reference_patterns = [str(x).strip() for x in (sp.get("reference_patterns") or []) if str(x or "").strip()]
    reference_examples = sp.get("reference_examples") if isinstance(sp.get("reference_examples"), list) else []
    example_stems = [
        _clip(str((it or {}).get("stem") or "").strip(), 240)
        for it in reference_examples
        if isinstance(it, dict) and str((it or {}).get("stem") or "").strip()
    ][:3]

    payload: Dict[str, Any] = {
        "subject": subject,
        "topic": topic,
        "subject_family": family,
        "subject_seed_tags": list(bank.seed_tags or [])[:18],
        "subject_skills": list(bank.skills or [])[:18],
        "study_markdown_brief": _clip(str(sp.get("study_markdown") or "").strip(), 2200),
        "distilled_skills": [str(x).strip() for x in (sp.get("skills") or []) if str(x or "").strip()][:12],
        "forbidden_patterns": [str(x).strip() for x in (sp.get("forbidden_patterns") or []) if str(x or "").strip()][:10],
        "reference_patterns": reference_patterns[:8],
        "reference_example_stems": example_stems,
        "curriculum_context": curriculum_context_for_prompt(sp),
        "intuition_practice": practice_config,
        "seed_count": seed_count,
        "output_schema": {
            "seeds": [
                {
                    "concept": "string (核心创意/交叉点)",
                    "angle": "string (设问角度/推理切入点)",
                    "scenario": "string (可选：真实情境/物理过程/材料背景，避免堆砌)",
                    "seed_tag": "string (一句话标签，便于 beam-search 分桶)",
                    "skill_hint": "string (关键方法或能力点)",
                    "reasoning_hint": "string (关键推理结构/步骤分布)",
                    "novelty_note": "string (如何隐藏决定性结构并避免公式代入/完整方法泄露)",
                    "mother_question_demand": "string (母题本身要求学生发现什么隐藏关系；不得只是练习包中的附加思考)",
                    "topic_binding": "string (逐项说明 topic 中各内容限定如何直接进入母题条件与设问)",
                    "intuition_atom": {
                        "concept": "string (学生需要在脑中操作的知识对象)",
                        "internal_model": "string (希望学生形成的内部模型)",
                        "mental_action": "string (比较/移动/缩放/取极端/换表征等心智动作)",
                        "decisive_cue": "string (决定结论的结构线索)",
                        "expected_first_feel": "string (合理但尚未形式化的第一感觉)",
                        "common_false_intuition": "string (最值得校准的错误直觉)",
                        "formal_anchor": "string (验证第一感觉所需的最小证据)",
                        "transfer_mutation": "string (保留结构并改变至少两个表面特征)",
                        "boundary_flip": "string (改变何种关键条件会使结论翻转)",
                        "feedback": "string (如何反馈以帮助学生修正内部模型)",
                    },
                }
            ]
        },
    }

    # Keep system prompt compact: this stage is short and shouldn't bloat tokens.
    role = str(bank.system_role or "").strip() or "You are a senior high-school curriculum researcher."
    selected_goal_contract = ""
    if practice_config["practice_goal"] == "solution_appreciation":
        selected_goal_contract = (
            "  <selected_goal_contract>Because practice_goal=solution_appreciation, every seed is invalid unless "
            "mother_question_demand explicitly makes the learner produce, distinguish, and compare two genuinely "
            "different routes or representations as a scored part of the mother question. Do not name the two "
            "routes in advance; ask the learner to find them. First ensure the underlying object still requires a "
            "non-mechanical symmetry, invariant, relationship, boundary, or representation insight.</selected_goal_contract>\n"
        )
    system_content = (
        _prompt("question.brainstorm.v1")
        + "\n\n"
        f"<role>{role}</role>\n"
        "<task>Design intuition atoms for student self-practice. Each atom must make a learner predict, expose an internal model, verify it briefly, and transfer it. Do not write final questions.</task>\n"
        "<requirements>\n"
        "  <count>Output 4-8 diverse intuition atoms as strict JSON.</count>\n"
        "  <seed_quality>Each seed must be implementable as a solvable question with clear conditions and conclusions, not a vague topic.\n"
        "    concept must specify knowledge-point intersections or condition combinations; angle must specify the reasoning entry point.</seed_quality>\n"
        "  <novelty>Do not create textbook-example-with-different-numbers ideas. Each seed must include at least one original design point:\n"
        "    cross-knowledge intersection / unusual constraints / real-scenario modeling / reverse questioning / open exploration / parameter-variation driven reasoning.\n"
        "    Keep idea directions diverse within the same batch to avoid homogeneity.</novelty>\n"
        "  <scenario_design>If an application scenario is introduced, it must support subject modeling rather than serve as decoration.\n"
        "    Data must be reasonable, verifiable, and convertible into clear mathematical/subject conditions.</scenario_design>\n"
        "  <intuition>Intuition is a trainable internal representation, not fast guessing or a memorized problem type.\n"
        "    The decisive cue must support a first prediction before full calculation, and formal_anchor must provide a short correction signal.</intuition>\n"
        "  <low_floor_high_thought>Low entry means curriculum-accessible prerequisites and a short final check; it does not mean low thinking.\n"
        "    Reject an atom whose eventual question can be completed by substituting data into a named or displayed formula, following a fully prescribed method, or doing arithmetic without first inferring a hidden relationship.</low_floor_high_thought>\n"
        "  <hidden_structure>Keep decisive_cue in the private design atom. The eventual stem may contain evidence from which the learner can discover it,\n"
        "    but must not state the invariant, symmetry, boundary mechanism, representation switch, or complete solution route that is supposed to be noticed.</hidden_structure>\n"
        "  <mother_question>The final mother question must itself require the target mental action even if its intuition packet is removed.\n"
        "    Fill mother_question_demand with the non-routine demand carried by the stem: what relationship must be inferred, representation reorganized, invariant detected,\n"
        "    boundary located, counterexample constructed, or genuinely different routes compared. A routine calculation followed by an intuition-themed packet is invalid.</mother_question>\n"
        "  <topic_binding>Treat every substantive clause in the requested topic as a hard design constraint, not a menu of optional keywords.\n"
        "    Fill topic_binding by mapping each clause to a condition or scored demand in the mother question. If topic explicitly requests symmetry and invariants,\n"
        "    the learner must actually discover or use a symmetry and an invariant; mentioning those words only in the packet, feedback, or solution commentary does not count.</topic_binding>\n"
        "  <subpart_integrity>Do not plan standard preliminary subparts that pre-solve the insight, such as first finding parameters/general terms and then substituting them into\n"
        "    a sum, extremum, probability, or formula task. Every retained subpart must contribute evidence, test a conjecture, expose a boundary, or compare representations;\n"
        "    removing a subpart must not reveal that it was only mechanical scaffolding.</subpart_integrity>\n"
        "  <structural_depth>Require a genuine mental reorganization: infer a non-explicit relationship, change representation, detect an invariant or symmetry,\n"
        "    locate a boundary, or construct/test a counterexample. The insight may be compact and must remain inside curriculum scope.</structural_depth>\n"
        "  <transfer>transfer_mutation must preserve the target mental action while changing at least one relationship, constraint direction, boundary regime, or representation,\n"
        "    plus a surface feature when useful. Do not merely change numbers, names, or story context.</transfer>\n"
        "  <appreciation>If the atom supports solution comparison, propose two genuinely different representations or reasoning routes, such as algebraic versus geometric\n"
        "    or local versus global. Do not compare cosmetic rewrites of one formula or a formula substitution with the same substitution written longer.</appreciation>\n"
        "  <appreciation_not_rescue>solution_appreciation cannot rescue a routine base task. First require a structurally non-routine mother question; only then may appreciation\n"
        "    compare routes that illuminate that same hidden structure. For medium difficulty, reject 'given a general term, find the extremum of S_n, then compare two standard methods'.</appreciation_not_rescue>\n"
        + selected_goal_contract
        + "  <rejection_examples>Reject direct formula substitution, a stem that says exactly which complete methods to use, number-only transfer,\n"
        "    and a comparison whose preferred answer is already announced in the prompt.</rejection_examples>\n"
        "  <subject_adapter>For math use representation, invariants, symmetry, boundary, estimation, or counterexamples.\n"
        "    For physics use process, dimensions, limits, and graph direction; for chemistry use particle models, conservation, and equilibrium direction;\n"
        "    for biology use systems, feedback, and causal evidence; for language subjects use discourse expectation followed by textual evidence.</subject_adapter>\n"
        "  <self_practice>Prefer accessible tasks with one non-obvious decisive insight and a short verification. Do not force long or advanced derivations,\n"
        "    but never reduce the central mathematical or subject-specific action to execution of an already supplied recipe.</self_practice>\n"
        "  <curriculum>Respect curriculum_context: question_requirements, knowledge_scope, and prerequisites.</curriculum>\n"
        "  <reference_use>If reference patterns/examples are provided, learn only their question structure and wording style. Do not copy original values or conclusions.\n"
        "    You may borrow the way conditions are combined, but must apply an innovative transformation.</reference_use>\n"
        "</requirements>\n"
        "<output_format>Output a strict JSON object only. Do not output Markdown or explanations.</output_format>"
    )

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.55,
        max_tokens=0,
        req_id_prefix="ql_brainstorm",
        retries=2,
        raise_on_fail=False,
        stage_id="brainstorm",
        stage_label="直觉原子设计",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )

    obj = _extract_json_obj(text)
    seeds_any = obj.get("seeds") if isinstance(obj, dict) else None
    seeds_raw = seeds_any if isinstance(seeds_any, list) else []

    out: List[dict] = []
    seen_keys: set[str] = set()
    for item in seeds_raw:
        normalized = _normalize_seed(item)
        if not normalized:
            continue
        key = json.dumps(
            {
                "concept": normalized.get("concept"),
                "angle": normalized.get("angle"),
                "seed_tag": normalized.get("seed_tag"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(normalized)
        if len(out) >= seed_count:
            break

    return out[:seed_count]
