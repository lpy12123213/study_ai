from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.question_library.subject_knowledge import get_subject_bank, infer_subject_family


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
    }


async def brainstorm_creative_seeds(
    source_pack: dict,
    *,
    seed_count: int = 8,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> List[dict]:
    """Brainstorm 6-10 creative seeds before beam-search spec expansion.

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

    seed_count = max(6, min(int(seed_count or 8), 10))

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
                }
            ]
        },
    }

    # Keep system prompt compact: this stage is short and shouldn't bloat tokens.
    role = str(bank.system_role or "").strip() or "你是资深高中教研员。"
    system_content = (
        f"<role>{role}</role>\n"
        "<task>你要做的是\u201c出题创意构思\u201d——为后续正式出题提供高质量创意种子，不是直接出题。</task>\n"
        "<requirements>\n"
        "  <count>输出 6-10 个创意种子（严格 JSON）。</count>\n"
        "  <seed_quality>每个种子必须可落地成一道可解的题：要能对应到明确的条件与结论，而不是空泛主题。\n"
        "    concept 要具体到知识点交叉/条件组合层面，angle 要明确推理切入点。</seed_quality>\n"
        "  <novelty>严禁\u201c教材例题换数字\u201d式创意；每个种子至少体现以下一项原创性：\n"
        "    跨知识点交叉 / 非常规约束条件 / 真实情境建模 / 逆向设问 / 开放性探究 / 参数变化驱动。\n"
        "    同一批种子内创意方向尽量分散，避免同质化。</novelty>\n"
        "  <scenario_design>若引入应用情境，情境必须服务于学科建模（非纯粹装饰），\n"
        "    数据要合理、可验证，能转化为明确的数学/学科条件。</scenario_design>\n"
        "  <thinking_depth>优先产出需要多步推导、参数讨论或构造性思维的创意，\n"
        "    避免\u201c一步到位\u201d的纯记忆/纯套公式型创意。</thinking_depth>\n"
        "  <discrimination>考虑区分度：好的创意应让中等生与优秀生呈现不同解题路径或完成度。</discrimination>\n"
        "  <reference_use>如果给了参考规律/例题，只学习其\u201c出题结构与设问风格\u201d，严禁复刻原题数值与结论。\n"
        "    可以借鉴参考题的条件组合方式，但必须在此基础上做创新变形。</reference_use>\n"
        "</requirements>\n"
        "<output_format>严格输出 JSON object，不要 Markdown，不要解释。</output_format>"
    )

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.45,
        max_tokens=0,
        req_id_prefix="ql_brainstorm",
        retries=2,
        raise_on_fail=False,
        stage_id="brainstorm",
        stage_label="创意发散",
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

