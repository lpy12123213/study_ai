from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.curriculum_reference import (
    CURRICULUM_STANDARD,
    get_curriculum_reference_article,
)
from backend.generation.question_library.gen_llm import _chat_json_with_reasoning, _extract_json_obj
from backend.generation.question_library.gen_utils import ReasoningEventHandler, _clip
from backend.generation.question_library.subject_knowledge import infer_subject_family
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry

_BASELINES: Dict[str, Dict[str, Any]] = {
    "math": {
        "question_requirements": [
            "突出数学思维过程，避免纯记忆性、机械刷题式设问",
            "考查逻辑推理与数学运算的规范表达，关键步骤可复现",
            "可在真实或合理情境中建模，但情境必须服务于数学本质",
            "允许参数讨论、分类讨论、构造与反证等深度思维，但条件须充分且无歧义",
            "不超纲：不使用大学或未学工具/结论替代高中解法",
        ],
        "core_competencies": ["数学抽象", "逻辑推理", "数学建模", "数学运算", "直观想象", "数据分析"],
    },
    "physics": {
        "question_requirements": [
            "强调物理观念、科学思维与科学探究，过程建模优先于套公式",
            "受力分析、守恒条件、单位量纲与方向符号须自洽",
            "实验题应体现控制变量、对照与误差分析意识",
            "情境数据合理，物理过程分段清晰，临界条件可判定",
            "不超纲：不使用未学模型或超出课标范围的近似处理",
        ],
        "core_competencies": ["物理观念", "科学思维", "科学探究", "科学态度与责任"],
    },
    "chemistry": {
        "question_requirements": [
            "考查宏观现象与微观本质的联系，方程式与守恒关系规范",
            "强调证据推理与模型认知，避免只背结论不讲原理",
            "实验与工业流程题须条件完整、现象与推断对应",
            "平衡、速率、电化学等题应体现变量分析与定量关系",
            "不超纲：不使用未学反应机理或超出课标范围的复杂计算",
        ],
        "core_competencies": ["宏观辨识与微观探析", "变化观念与平衡思想", "证据推理与模型认知", "科学探究与创新意识"],
    },
    "biology": {
        "question_requirements": [
            "强调生命观念与科学思维，答案须有证据链支撑",
            "实验探究题须体现对照、变量控制与结果解释",
            "遗传、调节、生态等题应体现系统性与层次性",
            "图表信息题要求读图准确、机制解释合理",
            "不超纲：不引入未学分子机制或超出课标范围的实验技术细节",
        ],
        "core_competencies": ["生命观念", "科学思维", "科学探究", "社会责任"],
    },
    "chinese": {
        "question_requirements": [
            "阅读题答案须依托文本证据，避免空泛套话",
            "考查语言建构与审美鉴赏、思维发展与提升、文化传承与理解",
            "设问边界清晰，概括/分析/评价等动词要求准确对应",
            "文言文、诗歌鉴赏须结合语境与手法，不作无依据推断",
            "写作/表达题立意准确、结构清楚、语体得体",
        ],
        "core_competencies": ["语言建构与运用", "思维发展与提升", "审美鉴赏与创造", "文化传承与理解"],
    },
    "english": {
        "question_requirements": [
            "阅读/完形/七选五等题强调语篇理解与定位依据",
            "语法题须语义与结构双线校验，答案可解释",
            "写作/续写强调要点覆盖、衔接手段与语域得体",
            "词汇辨析与词义猜测须结合语境证据",
            "不超纲：不使用超出课标要求的生僻词汇或复杂语法结构",
        ],
        "core_competencies": ["语言能力", "文化意识", "思维品质", "学习能力"],
    },
    "generic": {
        "question_requirements": [
            "突出学科思维与能力考查，避免纯记忆或模板化换数",
            "条件充分、表述规范、答案唯一且可验证",
            "设问与难度匹配，体现区分度",
            "不超纲：严格限定在指定知识点与学段范围内",
        ],
        "core_competencies": ["学科思维", "知识应用", "分析推理", "规范表达"],
    },
}


def _normalize_string_list(value: Any, *, limit: int = 16) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _normalize_scope(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        return {"in_scope": [], "out_of_scope": []}
    return {
        "in_scope": _normalize_string_list(value.get("in_scope") or value.get("included") or [], limit=20),
        "out_of_scope": _normalize_string_list(value.get("out_of_scope") or value.get("excluded") or [], limit=16),
    }


def get_static_curriculum_baseline(subject: str) -> dict:
    family = infer_subject_family(subject)
    baseline = dict(_BASELINES.get(family) or _BASELINES["generic"])
    return {
        "curriculum_standard": CURRICULUM_STANDARD,
        "question_requirements": list(baseline.get("question_requirements") or []),
        "core_competencies": list(baseline.get("core_competencies") or []),
        "knowledge_scope": {"in_scope": [], "out_of_scope": []},
        "prerequisites": [],
    }


def normalize_curriculum_context(raw: Any, *, subject: str = "") -> dict:
    baseline = get_static_curriculum_baseline(subject)
    if not isinstance(raw, dict):
        return baseline

    question_requirements = _normalize_string_list(raw.get("question_requirements") or [], limit=16)
    core_competencies = _normalize_string_list(raw.get("core_competencies") or [], limit=10)
    prerequisites = _normalize_string_list(raw.get("prerequisites") or [], limit=16)
    knowledge_scope = _normalize_scope(raw.get("knowledge_scope"))

    if not question_requirements:
        question_requirements = list(baseline.get("question_requirements") or [])
    if not core_competencies:
        core_competencies = list(baseline.get("core_competencies") or [])

    return {
        "curriculum_standard": str(raw.get("curriculum_standard") or CURRICULUM_STANDARD).strip() or CURRICULUM_STANDARD,
        "question_requirements": question_requirements,
        "core_competencies": core_competencies,
        "knowledge_scope": knowledge_scope,
        "prerequisites": prerequisites,
    }


def curriculum_context_for_prompt(source_pack: dict) -> dict:
    sp = source_pack if isinstance(source_pack, dict) else {}
    subject = str(sp.get("subject") or "").strip()
    normalized = normalize_curriculum_context(
        {
            "curriculum_standard": sp.get("curriculum_standard"),
            "question_requirements": sp.get("question_requirements"),
            "core_competencies": sp.get("core_competencies"),
            "knowledge_scope": sp.get("knowledge_scope"),
            "prerequisites": sp.get("prerequisites"),
        },
        subject=subject,
    )
    knowledge_points = _normalize_string_list(sp.get("knowledge_points") or [], limit=12)
    if knowledge_points:
        scope = dict(normalized.get("knowledge_scope") or {})
        in_scope = list(scope.get("in_scope") or [])
        for item in knowledge_points:
            if item not in in_scope:
                in_scope.append(item)
        normalized["knowledge_scope"] = {
            "in_scope": in_scope[:20],
            "out_of_scope": list(scope.get("out_of_scope") or [])[:16],
        }
    normalized["reference_article"] = get_curriculum_reference_article()
    return normalized


def enrich_source_pack_with_curriculum(source_pack: dict, curriculum: dict) -> dict:
    base = dict(source_pack or {})
    ctx = normalize_curriculum_context(curriculum, subject=str(base.get("subject") or "").strip())
    base["curriculum_standard"] = ctx["curriculum_standard"]
    base["question_requirements"] = list(ctx.get("question_requirements") or [])
    base["core_competencies"] = list(ctx.get("core_competencies") or [])
    base["knowledge_scope"] = dict(ctx.get("knowledge_scope") or {"in_scope": [], "out_of_scope": []})
    base["prerequisites"] = list(ctx.get("prerequisites") or [])
    return base


def _build_curriculum_system_prompt() -> str:
    article = get_curriculum_reference_article()
    return create_default_prompt_registry().render(
        "question.curriculum_context.v1",
        curriculum_reference_article=article,
    ).content


async def build_curriculum_context(
    *,
    subject: str,
    topic: str,
    knowledge_points: Optional[List[str]] = None,
    grade_id: str = "",
    textbook_version_id: str = "",
    study_markdown: str = "",
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    kp_labels = _normalize_string_list(knowledge_points or [], limit=12)
    baseline = get_static_curriculum_baseline(subj)

    if not subj and not top and not kp_labels:
        return baseline

    if not is_llm_configured():
        ctx = dict(baseline)
        if kp_labels:
            ctx["knowledge_scope"] = {"in_scope": kp_labels, "out_of_scope": []}
        return ctx

    payload = {
        "curriculum_standard": CURRICULUM_STANDARD,
        "subject": subj,
        "topic": top,
        "knowledge_points": kp_labels,
        "grade_id": str(grade_id or "").strip(),
        "textbook_version_id": str(textbook_version_id or "").strip(),
        "study_markdown_brief": _clip(str(study_markdown or "").strip(), 3000),
        "baseline_question_requirements": baseline.get("question_requirements") or [],
        "baseline_core_competencies": baseline.get("core_competencies") or [],
        "output_schema": {
            "curriculum_standard": f"string (默认 {CURRICULUM_STANDARD})",
            "question_requirements": "string[] (新课标下的出题要求：学业质量、考查方式、难度边界、避免事项，≤12条)",
            "core_competencies": "string[] (应体现的核心素养/能力维度，≤8条)",
            "knowledge_scope": {
                "in_scope": "string[] (本题/本批次应覆盖的知识范围，≤16条)",
                "out_of_scope": "string[] (明确不应涉及的超纲或偏题内容，≤10条)",
            },
            "prerequisites": "string[] (解题所需前置知识与技能，≤12条)",
        },
    }

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": _build_curriculum_system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_curriculum",
        retries=2,
        raise_on_fail=False,
        stage_id="curriculum_context",
        stage_label="课标对齐",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
    )

    obj = _extract_json_obj(text)
    ctx = normalize_curriculum_context(obj, subject=subj)
    if kp_labels and not (ctx.get("knowledge_scope") or {}).get("in_scope"):
        ctx["knowledge_scope"] = {
            "in_scope": kp_labels,
            "out_of_scope": list((ctx.get("knowledge_scope") or {}).get("out_of_scope") or []),
        }
    return ctx
