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
    topic = str(sp.get("topic") or "").strip()
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
                    "novelty_note": "string (避免模板的具体做法)",
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
        "  <transfer>transfer_mutation must preserve the decisive structure while changing at least two surface features. Do not merely change numbers.</transfer>\n"
        "  <subject_adapter>For math use representation, invariants, symmetry, boundary, estimation, or counterexamples.\n"
        "    For physics use process, dimensions, limits, and graph direction; for chemistry use particle models, conservation, and equilibrium direction;\n"
        "    for biology use systems, feedback, and causal evidence; for language subjects use discourse expectation followed by textual evidence.</subject_adapter>\n"
        "  <self_practice>Prefer low-entry tasks with one decisive insight and a short verification. Do not force long or advanced derivations.</self_practice>\n"
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
