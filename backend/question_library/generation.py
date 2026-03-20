from __future__ import annotations

import inspect
import json
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.llm_client import chat_completion_text, is_llm_configured
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE

logger = get_logger(__name__)

DEFAULT_SEARCH_CONFIG = {
    "preset": "balanced-creative",
    "depth": 4,
    "beam_width": 12,
    "expand_budget": 140,
    "skill_branch_factor": 4,
    "reasoning_branch_factor": 4,
    "trap_branch_factor": 3,
    "surface_branch_factor": 3,
    "difficulty_match_weight": 0.24,
    "novelty_weight": 0.24,
    "skill_coverage_weight": 0.2,
    "solvability_weight": 0.2,
    "ambiguity_penalty": 0.26,
    "template_penalty": 0.16,
    "judge_pass_score": 70,
    "difficulty_tolerance": 0.22,
    "solver_consensus_n": 2,
    "max_repair_rounds": 2,
    # Only attempt a repair when the judge score is close to the pass floor.
    # Low-quality "template" questions should be discarded rather than rewritten.
    "repair_score_band": 20,
    "repair_min_score": 50,
    "answer_mismatch_penalty": 12,
    "ambiguity_penalty_score": 8,
    "judge_require_pass_flag": False,
    "realize_min_max_tokens": 5000,
    "drafts_per_spec": 3,
}

_MATH_SEED_TAGS = [
    "参数变化",
    "分类讨论",
    "构造反例",
    "数形结合",
    "条件反推",
    "综合应用",
]

_MATH_SKILLS = [
    "概念辨析",
    "性质判定",
    "计算推导",
    "条件反推",
    "参数讨论",
    "构造反例",
    "综合应用",
]

_MATH_REASONING_PATTERNS = [
    "参数变化分析 + 分类讨论",
    "构造函数/构造反例",
    "等价转化 + 多步推导",
    "数形结合 + 关键不等式",
    "反证法/归谬",
    "分离变量/配方法 + 结构化求解",
]

_MATH_TRAPS = [
    "忽略定义域/取值范围",
    "边界点漏判",
    "把必要条件当充分条件",
    "符号讨论遗漏",
    "条件转化方向弄反",
    "极值/最值概念混淆",
]

_MATH_SURFACES = [
    "参数变化探究题",
    "带约束的综合解答题",
    "反例辨析题",
    "分类讨论压轴题",
    "几何意义转化题",
    "开放性探究题",
]

StageEventHandler = Optional[Callable[[dict], Awaitable[None] | None]]


def _is_math_subject(subject: str) -> bool:
    s = str(subject or "").strip()
    return "数学" in s or s.lower() in {"math", "mathematics"}


def _clip_unique(options: List[str], n: int) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for it in options or []:
        t = str(it or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= n:
            break
    return out


def _expand_field(
    specs: List[dict],
    *,
    field: str,
    layer: str,
    options: List[str],
    branch_factor: int,
    budget: int,
) -> List[dict]:
    out: List[dict] = []
    max_children = max(1, int(branch_factor or 1))
    max_total = max(1, int(budget or 1))
    opts = _clip_unique(options, max_children)
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        base = dict(spec)
        for opt in opts:
            child = dict(base)
            child[field] = opt
            child["layer"] = layer
            parent_id = str(base.get("spec_id") or "").strip() or "spec"
            child["spec_id"] = f"{parent_id}/{field}:{abs(hash(opt)) % 997}"
            out.append(child)
            if len(out) >= max_total:
                return out
    return out


def build_ai_question_id(*, now_ts: float | None = None, suffix: str = "") -> str:
    ts = time.localtime(now_ts if now_ts is not None else time.time())
    stamp = time.strftime("%Y%m%d%H%M", ts)
    suf = (suffix or "").strip() or "00000000"
    suf = suf[:8]
    return f"ai_{stamp}_{suf}"[:50]


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "")
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _summarize_candidate_sample(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        "spec_id": str(item.get("spec_id") or "").strip(),
        "seed_tag": str(item.get("seed_tag") or "").strip(),
        "skill": str(item.get("skill") or "").strip(),
        "reasoning": str(item.get("reasoning") or "").strip(),
        "trap": str(item.get("trap") or "").strip(),
        "surface": str(item.get("surface") or "").strip(),
        "stem_preview": _clip(str(item.get("stem") or "").strip(), 120),
    }


async def _emit_stage_event(
    on_stage_event: StageEventHandler,
    *,
    phase: str,
    label: str,
    progress: float,
    stats: Optional[dict] = None,
    sample: Optional[dict] = None,
) -> None:
    if on_stage_event is None:
        return

    payload = {
        "phase": str(phase or "").strip(),
        "label": str(label or "").strip(),
        "progress": float(progress),
        "stats": dict(stats or {}),
    }
    if sample:
        payload["sample"] = dict(sample)

    try:
        result = on_stage_event(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


def _extract_json_obj(text: str) -> Dict[str, Any]:
    value = _extract_json_value(text)
    return value if isinstance(value, dict) else {}


def _strip_json_fence(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw).lstrip()
        raw = re.sub(r"\s*```$", "", raw).rstrip()
    return raw


def _repair_json_backslashes(raw: str) -> str:
    """
    Best-effort repair for "almost JSON" emitted by some models when LaTeX is embedded
    in JSON strings (e.g. `\\( ... \\)` is output as `\\( ... \\)` without JSON escaping,
    or commands like `\\frac` are emitted as `\\frac` where `\\f` becomes a JSON escape).

    Strategy: inside JSON string literals only, escape backslashes that would otherwise
    create invalid or unintended JSON escapes, while preserving legit escapes like `\\n`.
    """

    s = str(raw or "")
    if not s:
        return s

    out: list[str] = []
    in_str = False
    i = 0
    hex_chars = set("0123456789abcdefABCDEF")

    while i < len(s):
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue

        # Inside a string literal.
        if ch == '"':
            out.append(ch)
            in_str = False
            i += 1
            continue

        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        # Backslash inside a string: decide whether it is a valid JSON escape.
        if i + 1 >= len(s):
            out.append("\\\\")
            i += 1
            continue

        nxt = s[i + 1]

        # Always keep valid structural escapes.
        if nxt in {'"', "\\", "/"}:
            out.append("\\")
            out.append(nxt)
            i += 2
            continue

        if nxt in {"b", "f", "n", "r", "t"}:
            # JSON escapes like \\n are valid, but LaTeX commands frequently start with
            # these letters (e.g. \\neq, \\theta, \\frac). If the escape is followed by
            # an ASCII letter, assume it's LaTeX and escape the backslash.
            after = s[i + 2] if (i + 2) < len(s) else ""
            if after.isascii() and after.isalpha():
                out.append("\\\\")
                out.append(nxt)
                i += 2
                continue
            out.append("\\")
            out.append(nxt)
            i += 2
            continue

        if nxt == "u":
            # Keep \\uXXXX unicode escapes, otherwise treat as LaTeX (e.g. \\underline).
            if (i + 5) < len(s):
                hex4 = s[i + 2 : i + 6]
                if len(hex4) == 4 and all(c in hex_chars for c in hex4):
                    out.append("\\")
                    out.append("u")
                    out.append(hex4)
                    i += 6
                    continue
            out.append("\\\\")
            out.append("u")
            i += 2
            continue

        # Invalid JSON escape (common with LaTeX like \\(, \\[, \\alpha, etc.)
        out.append("\\\\")
        i += 1

    return "".join(out)


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    return default


def _resolve_realize_max_tokens() -> int:
    base = int(LESSON_PLAN_MAX_TOKENS)
    minimum = int(DEFAULT_SEARCH_CONFIG.get("realize_min_max_tokens") or 5000)
    raw = str(os.getenv("QUESTION_LIBRARY_REALIZE_MAX_TOKENS") or "").strip()
    if raw:
        try:
            minimum = max(2000, int(raw))
        except Exception:
            minimum = int(DEFAULT_SEARCH_CONFIG.get("realize_min_max_tokens") or 5000)
    return max(base, minimum)


def _extract_json_value(text: str) -> Any:
    raw = _strip_json_fence(text)
    if not raw:
        return {}

    for candidate in (raw, raw[raw.find("{") : raw.rfind("}") + 1], raw[raw.find("[") : raw.rfind("]") + 1]):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            pass
        try:
            repaired = _repair_json_backslashes(candidate)
            if repaired != candidate:
                return json.loads(repaired)
        except Exception:
            continue
    return {}


def _normalize_question_text(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(item or "").strip() for item in value if str(item or "").strip()]
        return "\n".join(parts).strip()
    return str(value or "").strip()


def _extract_question_items(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("questions", "题目", "试题"):
        items = payload.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]

    if any(key in payload for key in ("stem", "题干", "question", "answer", "答案", "analysis", "解析")):
        return [payload]
    return []


def _normalize_question_item(q: dict, spec: dict) -> Optional[dict]:
    if not isinstance(q, dict):
        return None

    stem = _normalize_question_text(q.get("stem") or q.get("题干") or q.get("question") or q.get("题目"))
    ans = _normalize_question_text(q.get("answer") or q.get("答案") or q.get("参考答案"))
    ana = _normalize_question_text(q.get("analysis") or q.get("解析") or q.get("解答"))
    if not stem or not ans or not ana:
        return None

    return {
        "stem": stem,
        "answer": ans,
        "analysis": ana,
        "spec_id": str((spec or {}).get("spec_id") or "").strip(),
        "skill": str((spec or {}).get("skill") or "").strip(),
        "reasoning": str((spec or {}).get("reasoning") or "").strip(),
        "trap": str((spec or {}).get("trap") or "").strip(),
        "surface": str((spec or {}).get("surface") or "").strip(),
        "seed_tag": str((spec or {}).get("seed_tag") or "").strip(),
    }


async def build_source_pack(study_markdown: str, subject: str, topic: str) -> dict:
    subj = str(subject or "").strip()
    top = str(topic or "").strip()
    md = _clip(str(study_markdown or ""), 12000)

    base = {
        "subject": subj,
        "topic": top,
        "study_markdown": md,
        "facts": [],
        "skills": [],
        "common_mistakes": [],
        "forbidden_patterns": [],
    }

    if not is_llm_configured() or not md.strip():
        return base

    payload = {
        "subject": subj,
        "topic": top,
        "study_markdown": md,
        "output_schema": {
            "facts": "string[] (关键事实/公式/结论)",
            "skills": "string[] (能力点/解题方法)",
            "common_mistakes": "string[] (常见误区)",
            "forbidden_patterns": "string[] (模板题/低质量套路的特征，用于避免生成)",
        },
    }

    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": "你是教研员助手，擅长把学习资料压缩成可用于出题的结构化要点。请严格输出 JSON object。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=1600,
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_distill",
    )

    obj = _extract_json_obj(text)
    facts = [str(x).strip() for x in (obj.get("facts") or []) if str(x or "").strip()]
    skills = [str(x).strip() for x in (obj.get("skills") or []) if str(x or "").strip()]
    mistakes = [str(x).strip() for x in (obj.get("common_mistakes") or []) if str(x or "").strip()]
    forbidden = [str(x).strip() for x in (obj.get("forbidden_patterns") or []) if str(x or "").strip()]

    base["facts"] = facts[:24]
    base["skills"] = skills[:24]
    base["common_mistakes"] = mistakes[:24]
    base["forbidden_patterns"] = forbidden[:24]
    return base


def seed_root_specs(source_pack: dict, count: int, difficulty: str, question_type: str) -> List[dict]:
    subj = str((source_pack or {}).get("subject") or "").strip()
    top = str((source_pack or {}).get("topic") or "").strip()
    specs: List[dict] = []
    # Root seeding should create a small, diverse set of candidates (4-6) before expansion.
    target = max(1, min(int(count or 1), 10))
    n = max(4, min(6, max(4, target)))
    seed_tags = _MATH_SEED_TAGS if _is_math_subject(subj) else ["覆盖能力", "变化分析", "综合推理", "反例辨析", "条件反推", "应用迁移"]
    seed_tags = _clip_unique(seed_tags, n)
    for i, tag in enumerate(seed_tags):
        specs.append(
            {
                "spec_id": f"spec_{i + 1}",
                "subject": subj,
                "topic": top,
                "difficulty": str(difficulty or "").strip(),
                "question_type": str(question_type or "").strip(),
                "layer": "root",
                "seed_tag": tag,
            }
        )
    return specs


def expand_skill_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = _MATH_SKILLS if _is_math_subject(subj) else ["概念辨析", "性质判定", "计算推导", "条件反推", "综合应用"]
    return _expand_field(
        specs,
        field="skill",
        layer="skill",
        options=options,
        branch_factor=int((config or {}).get("skill_branch_factor") or DEFAULT_SEARCH_CONFIG["skill_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_reasoning_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = (
        _MATH_REASONING_PATTERNS
        if _is_math_subject(subj)
        else ["多步推导", "分类讨论", "变化分析", "构造反例", "等价转化", "综合推理"]
    )
    return _expand_field(
        specs,
        field="reasoning",
        layer="reasoning",
        options=options,
        branch_factor=int((config or {}).get("reasoning_branch_factor") or DEFAULT_SEARCH_CONFIG["reasoning_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_trap_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = _MATH_TRAPS if _is_math_subject(subj) else ["边界遗漏", "条件方向错误", "概念混淆", "范围忽略"]
    return _expand_field(
        specs,
        field="trap",
        layer="trap",
        options=options,
        branch_factor=int((config or {}).get("trap_branch_factor") or DEFAULT_SEARCH_CONFIG["trap_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def expand_surface_layer(specs: List[dict], config: dict) -> List[dict]:
    if not specs:
        return []
    subj = str((specs[0] or {}).get("subject") or "").strip()
    options = _MATH_SURFACES if _is_math_subject(subj) else ["综合题", "探究题", "应用题", "辨析题"]
    return _expand_field(
        specs,
        field="surface",
        layer="surface",
        options=options,
        branch_factor=int((config or {}).get("surface_branch_factor") or DEFAULT_SEARCH_CONFIG["surface_branch_factor"]),
        budget=int((config or {}).get("expand_budget") or DEFAULT_SEARCH_CONFIG["expand_budget"]),
    )


def score_spec(spec: dict, source_pack: dict, config: dict) -> dict:
    _ = source_pack
    out = dict(spec or {})
    difficulty = str(out.get("difficulty") or "").strip()
    skill = str(out.get("skill") or "").strip()
    reasoning = str(out.get("reasoning") or "").strip()
    trap = str(out.get("trap") or "").strip()
    surface = str(out.get("surface") or "").strip()

    # Normalize sub-scores to [0, 1].
    if "困难" in difficulty or "压轴" in difficulty:
        difficulty_match = 1.0
    elif "中等" in difficulty:
        difficulty_match = 0.75
    elif "简单" in difficulty:
        difficulty_match = 0.45
    else:
        difficulty_match = 0.65

    reasoning_depth = 0.25
    for kw in ["分类", "参数", "构造", "反证", "多步", "数形", "综合"]:
        if kw in reasoning:
            reasoning_depth += 0.12
    reasoning_depth = min(1.0, reasoning_depth)

    novelty = 0.25
    for kw in ["参数", "反例", "探究", "变化", "开放", "压轴", "综合"]:
        if kw in (surface + " " + reasoning + " " + skill):
            novelty += 0.1
    novelty = min(1.0, novelty)

    skill_coverage = 0.35 + (0.25 if skill else 0.0) + (0.25 if reasoning else 0.0)
    skill_coverage = min(1.0, skill_coverage)

    solvability = 0.8
    if any(k in trap for k in ["多解", "歧义", "陷阱过多"]):
        solvability -= 0.25
    solvability = max(0.2, min(1.0, solvability))

    ambiguity_risk = 0.25
    if any(k in trap for k in ["定义域", "边界", "符号"]):
        ambiguity_risk += 0.15
    ambiguity_risk = min(1.0, ambiguity_risk)

    template_similarity = 0.15
    for kw in ["求单调区间", "直接求导", "套公式", "代入即可"]:
        if kw in reasoning or kw in surface:
            template_similarity += 0.25
    template_similarity = min(1.0, template_similarity)

    w_diff = float((config or {}).get("difficulty_match_weight") or 0.24)
    w_novel = float((config or {}).get("novelty_weight") or 0.24)
    w_skill = float((config or {}).get("skill_coverage_weight") or 0.2)
    w_solv = float((config or {}).get("solvability_weight") or 0.2)
    w_amb = float((config or {}).get("ambiguity_penalty") or 0.26)
    w_tpl = float((config or {}).get("template_penalty") or 0.16)

    score = (
        w_diff * difficulty_match
        + w_novel * novelty
        + w_skill * skill_coverage
        + w_solv * solvability
        - w_amb * ambiguity_risk
        - w_tpl * template_similarity
    )
    # Convert to a 0-100-ish scale for easier debugging.
    out["score"] = float(max(0.0, min(1.0, score)) * 100.0 + reasoning_depth * 8.0)
    return out


def beam_select(specs: List[dict], config: dict) -> List[dict]:
    bw = max(1, int((config or {}).get("beam_width") or DEFAULT_SEARCH_CONFIG["beam_width"]))
    scored: List[dict] = []
    for s in specs or []:
        if isinstance(s, dict):
            scored.append(dict(s))
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return scored[:bw]


async def realize_drafts(spec: dict, *, source_pack: dict, n: int = 2) -> List[dict]:
    if not is_llm_configured():
        return []

    subj = str((spec or {}).get("subject") or (source_pack or {}).get("subject") or "").strip() or "高中数学"
    topic = str((spec or {}).get("topic") or (source_pack or {}).get("topic") or "").strip()
    difficulty = str((spec or {}).get("difficulty") or "").strip()
    qtype = str((spec or {}).get("question_type") or "").strip()
    study_md = str((source_pack or {}).get("study_markdown") or "").strip()
    n = max(1, min(int(n or 1), 4))

    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"
    temperature = min(0.35, float(LESSON_PLAN_TEMPERATURE))
    max_tokens = _resolve_realize_max_tokens()

    # First attempt: generate `n` drafts in one shot.
    # If the response is truncated/invalid JSON (common with LaTeX-heavy content),
    # retry in a safer "short mode" that asks for only 1 question.
    for attempt in range(2):
        target_n = n if attempt == 0 else 1
        messages = build_generation_messages(
            subject=subj,
            topic=topic,
            difficulty=difficulty,
            question_type=qtype,
            study_markdown=study_md,
            count=target_n,
            spec=spec,
            source_pack=source_pack,
        )
        if attempt > 0:
            # Force a compact retry: keep the output short and avoid meta commentary
            # that tends to bloat the response and trigger truncation.
            messages = [
                {
                    "role": "system",
                    "content": (
                        "上一次输出可能被截断或不符合 JSON。现在请重新输出，只生成 1 道题，并严格控制长度："
                        "解析最多 6~8 行短句，不要写“陷阱/易错/点评/矛盾讨论/可行性分析”。"
                        "若发现条件会导致无解或矛盾，请直接换一个更合理的题目。"
                        "只输出严格 JSON object。"
                    ),
                },
                *messages,
            ]

        text = await chat_completion_text(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            reasoning={"effort": "high", "exclude": True},
            stream=False,
            raise_on_fail=True,
            retries=3,
            req_id_prefix="qlg",
        )

        qs = _extract_question_items(_extract_json_value(text))
        out: List[dict] = []
        for q in qs:
            normalized = _normalize_question_item(q, spec)
            if normalized is None:
                continue
            out.append(normalized)
            if len(out) >= n:
                break
        if out:
            return out

    return []


def build_generation_messages(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    study_markdown: str,
    count: int,
    spec: Optional[dict] = None,
    source_pack: Optional[dict] = None,
) -> List[Dict[str, str]]:
    sp = source_pack or {}
    forbid = [str(x).strip() for x in (sp.get("forbidden_patterns") or []) if str(x or "").strip()]
    mistakes = [str(x).strip() for x in (sp.get("common_mistakes") or []) if str(x or "").strip()]
    skills = [str(x).strip() for x in (sp.get("skills") or []) if str(x or "").strip()]

    payload = {
        "subject": subject,
        "topic": topic,
        "difficulty": difficulty,
        "question_type": question_type,
        "study_markdown": study_markdown,
        "count": count,
        "spec": {
            "seed_tag": str((spec or {}).get("seed_tag") or "").strip(),
            "skill": str((spec or {}).get("skill") or "").strip(),
            "reasoning": str((spec or {}).get("reasoning") or "").strip(),
            "trap": str((spec or {}).get("trap") or "").strip(),
            "surface": str((spec or {}).get("surface") or "").strip(),
        },
        "quality_hints": {
            "preferred_skills": skills[:10],
            "common_mistakes": mistakes[:10],
            "forbidden_patterns": forbid[:12],
            "length_budget": {
                # Hard-ish caps to keep JSON responses small enough to be reliably
                # parseable (avoid max_tokens truncation), especially on verbose models.
                "max_sub_questions": 2,
                "stem_max_chars": 520,
                "answer_max_chars": 360,
                "analysis_max_chars": 1100,
            },
            "must_have": [
                "多步推导 / 参数变化 / 分类讨论 / 构造反例 至少满足其一",
                "题目具有区分度，不是教材例题换皮",
                "解析要可复现但尽量精炼，结论要明确",
            ],
        },
        "output_schema": {
            "questions": [
                {
                    "stem": "string",
                    "answer": "string",
                    "analysis": "string",
                }
            ]
        },
    }

    system_content = (
        "你是资深高中教研员。请严格输出 JSON object，不要输出 Markdown，不要解释。"
        "所有数学公式必须使用 LaTeX 表达。"
        "行内公式必须写成 \\(...\\)，独立公式必须写成 \\[...\\]。"
        "严禁使用 $...$ 作为公式包裹。"
        "若题目需要表格、分布列、矩阵或分类列举，必须写成 LaTeX 的 array/matrix/cases 结构。"
        "禁止输出纯文本竖排表格或用换行假装表格。"
        "禁止输出图片公式、MathML、SVG、伪代码公式或自然语言替代公式。"
        "题干、答案、解析中的公式都必须遵守同一 LaTeX 规范。"
        "优先生成具有区分度的中高难题，避免模板题和一步到位的基础题。"
        "每道题最多 2 小问；控制长度，遵守 length_budget；避免输出大段冗长文字。"
        "解析只写必要推导步骤（建议 6~8 行短句），禁止输出“陷阱/易错/点评/矛盾讨论/可行性分析”等元文本。"
        "如发现题目条件会导致无解/矛盾/过长，请直接换一个更合理且可解的题目。"
        "务必保证 JSON 完整闭合、可被解析（不要输出截断的 JSON）。"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def build_regenerate_section_messages(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    study_markdown: str,
    section_key: str,
    stem: str,
    answer: str,
    analysis: str,
) -> List[Dict[str, str]]:
    normalized_key = str(section_key or "").strip() or "analysis"
    if normalized_key not in {"stem", "answer", "analysis"}:
        normalized_key = "analysis"

    payload = {
        "subject": subject,
        "topic": topic,
        "difficulty": difficulty,
        "question_type": question_type,
        "study_markdown": study_markdown,
        "section_key": normalized_key,
        "current_question": {
            "stem": stem,
            "answer": answer,
            "analysis": analysis,
        },
        "output_schema": {
            "section_key": normalized_key,
            "content": "string",
        },
    }

    system_content = (
        "你是资深高中教研员。请严格输出 JSON object，不要输出 Markdown，不要解释。"
        "所有数学公式必须使用 LaTeX 表达。"
        "行内公式必须写成 \\(...\\)，独立公式必须写成 \\[...\\]。"
        "若题目需要表格、分布列、矩阵或分类列举，必须写成 LaTeX 的 array/matrix/cases 结构。"
        "禁止输出纯文本竖排表格或用换行假装表格。"
        "禁止输出图片公式、MathML、SVG、伪代码公式或自然语言替代公式。"
        "请只重写被要求的那个 section，同时尽量保持其余 section 的知识点、难度和结论一致。"
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def regenerate_question_section(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    study_markdown: str,
    section_key: str,
    stem: str,
    answer: str,
    analysis: str,
) -> str:
    if not is_llm_configured():
        return ""

    messages = build_regenerate_section_messages(
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        study_markdown=study_markdown,
        section_key=section_key,
        stem=stem,
        answer=answer,
        analysis=analysis,
    )

    text = await chat_completion_text(
        messages=messages,
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=float(LESSON_PLAN_TEMPERATURE),
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="qlr",
    )

    obj = _extract_json_obj(text)
    content = str(obj.get("content") or "").strip()
    if content:
        return content

    fallback_key = str(section_key or "").strip()
    if fallback_key in {"stem", "answer", "analysis"}:
        return str(obj.get(fallback_key) or "").strip()
    return ""


async def solve_draft(stem: str, options: dict) -> dict:
    if not is_llm_configured():
        return {"match": False, "final_answer": "", "issues": ["llm_not_configured"], "summary": ""}

    subject = str((options or {}).get("subject") or "").strip()
    proposed_answer = str((options or {}).get("proposed_answer") or "").strip()

    payload = {
        "subject": subject,
        "stem": str(stem or "").strip(),
        "proposed_answer": proposed_answer,
        "output_schema": {
            "match": "bool (参考答案是否正确且与解题结论一致)",
            "final_answer": "string (你的最终答案，LaTeX)",
            "issues": "string[] (不一致/错误点)",
            "summary": "string",
        },
    }

    text = await chat_completion_text(
        messages=[
            {
                "role": "system",
                "content": "你是严谨的解题者。请独立解题并核对参考答案。严格输出 JSON object，不要输出解释。",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=1600,
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_solver",
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


async def check_ambiguity(draft: dict) -> dict:
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

    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": "你是审题专家，专门寻找歧义与多解风险。严格输出 JSON object。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=1400,
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_amb",
    )
    obj = _extract_json_obj(text)
    issues = obj.get("issues")
    return {
        "ambiguous": bool(obj.get("ambiguous")),
        "issues": list(issues or []) if isinstance(issues, list) else [],
        "summary": str(obj.get("summary") or "").strip(),
    }


async def judge_draft(draft: dict, spec: dict) -> dict:
    if not is_llm_configured():
        return {"pass": False, "overall_score": 0, "issues": ["llm_not_configured"], "summary": ""}

    subject = str((spec or {}).get("subject") or "").strip()
    difficulty = str((spec or {}).get("difficulty") or "").strip()
    requirements = (
        f"目标难度：{difficulty or '中等偏难'}。必须有新意与区分度，且符合 spec 的推理结构："
        f"{str((spec or {}).get('reasoning') or '').strip()}。"
    )
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

    text = await chat_completion_text(
        messages=[
            {
                "role": "system",
                "content": "你是资深教研员，负责评审试题质量与难度新意。严格输出 JSON object，不要输出Markdown或解释。",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="ql_judge",
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


async def refine_draft(draft: dict, judge: dict) -> dict:
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

    text = await chat_completion_text(
        messages=[
            {
                "role": "system",
                "content": "你是教研员修题助手。根据 issues 修复题目，保持难度与创新性，严格输出 JSON object。",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.25,
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_repair",
    )
    obj = _extract_json_obj(text)
    out = dict(draft or {})
    out["stem"] = str(obj.get("stem") or out.get("stem") or "").strip()
    out["answer"] = str(obj.get("answer") or out.get("answer") or "").strip()
    out["analysis"] = str(obj.get("analysis") or out.get("analysis") or "").strip()
    return out


def select_final(candidates: List[dict], count: int) -> List[dict]:
    n = max(1, min(int(count or 1), 20))
    out: List[dict] = []
    seen: set[str] = set()
    reasoning_used: set[str] = set()

    def _norm(text: str) -> str:
        t = re.sub(r"\s+", " ", str(text or "").strip())
        t = re.sub(r"\\\([\\s\\S]*?\\\)", " <m> ", t)
        t = re.sub(r"\\\[([\\s\\S]*?)\\\]", " <M> ", t)
        t = re.sub(r"\$\$([\\s\\S]*?)\$\$", " <M> ", t)
        t = re.sub(r"\$([^\n$]*?)\$", " <m> ", t)
        return t[:300]

    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        stem = str(c.get("stem") or "").strip()
        if not stem:
            continue
        key = _norm(stem)
        if key in seen:
            continue
        seen.add(key)

        reasoning = str(c.get("reasoning") or "").strip()
        # Prefer diversity in reasoning patterns first.
        if reasoning and reasoning in reasoning_used and len(out) < n:
            continue
        if reasoning:
            reasoning_used.add(reasoning)

        out.append(dict(c))
        if len(out) >= n:
            break

    # If diversity constraint filtered too much, fill remaining with best-effort uniques.
    if len(out) < n:
        for c in candidates or []:
            if not isinstance(c, dict):
                continue
            stem = str(c.get("stem") or "").strip()
            if not stem:
                continue
            key = _norm(stem)
            if key in { _norm(str(x.get("stem") or "")) for x in out }:
                continue
            out.append(dict(c))
            if len(out) >= n:
                break

    return out


async def generate_questions(
    *,
    source_pack: dict,
    count: int,
    difficulty: str,
    question_type: str,
    on_stage_event: StageEventHandler = None,
    config: Optional[dict] = None,
) -> List[dict]:
    cfg = dict(DEFAULT_SEARCH_CONFIG)
    if isinstance(config, dict):
        cfg.update(config)

    # Ensure source_pack contains distilled guidance for novelty/template avoidance.
    if not isinstance(source_pack, dict):
        source_pack = {}
    if not source_pack.get("skills") and not source_pack.get("forbidden_patterns"):
        try:
            source_pack = await build_source_pack(
                str(source_pack.get("study_markdown") or ""),
                str(source_pack.get("subject") or ""),
                str(source_pack.get("topic") or ""),
            )
        except Exception:
            pass

    beam_width = max(1, int(cfg.get("beam_width") or DEFAULT_SEARCH_CONFIG["beam_width"]))
    search_beam_width = max(beam_width, int(max(1, count or 1) * 2))

    def _score_and_beam(items: List[dict]) -> List[dict]:
        scored = [score_spec(s, source_pack, cfg) for s in items if isinstance(s, dict)]
        return beam_select(scored, {"beam_width": search_beam_width})

    root_specs = seed_root_specs(source_pack, count=count, difficulty=difficulty, question_type=question_type)
    root_beam = _score_and_beam(root_specs)
    skill_specs = expand_skill_layer(root_beam, cfg)
    skill_beam = _score_and_beam(skill_specs)
    reasoning_specs = expand_reasoning_layer(skill_beam, cfg)
    reasoning_beam = _score_and_beam(reasoning_specs)
    trap_specs = expand_trap_layer(reasoning_beam, cfg)
    trap_beam = _score_and_beam(trap_specs)
    surface_specs = expand_surface_layer(trap_beam, cfg)
    specs = _score_and_beam(surface_specs)

    per_spec = max(1, min(int(cfg.get("drafts_per_spec") or DEFAULT_SEARCH_CONFIG["drafts_per_spec"]), 4))
    max_specs = max(1, min(int(count or 1) * 3, max(4, search_beam_width)))
    specs = specs[:max_specs]

    await _emit_stage_event(
        on_stage_event,
        phase="spec_search",
        label="规格搜索",
        progress=20.0,
        stats={
            "root_specs": len(root_specs),
            "root_kept": len(root_beam),
            "skill_expanded": len(skill_specs),
            "reasoning_expanded": len(reasoning_specs),
            "trap_expanded": len(trap_specs),
            "surface_expanded": len(surface_specs),
            "kept_specs": len(specs),
            "search_beam_width": search_beam_width,
            "sample_seed_tags": _clip_unique([str((s or {}).get("seed_tag") or "") for s in specs], 4),
            "sample_skills": _clip_unique([str((s or {}).get("skill") or "") for s in specs], 4),
        },
        sample=_summarize_candidate_sample(specs[0]) if specs else None,
    )

    raw_candidates: List[dict] = []
    realize_failures = 0
    for spec in specs:
        try:
            ds = await realize_drafts(spec, source_pack=source_pack, n=per_spec)
        except Exception as exc:
            realize_failures += 1
            logger.warning(
                "question_library_realize_drafts_failed",
                extra={
                    "spec_id": str((spec or {}).get("spec_id") or "").strip(),
                    "topic": str((spec or {}).get("topic") or "").strip(),
                    "error": str(exc),
                },
            )
            continue
        for d in ds:
            if isinstance(d, dict):
                raw_candidates.append(dict(d))

    await _emit_stage_event(
        on_stage_event,
        phase="draft_realization",
        label="草稿生成",
        progress=55.0,
        stats={
            "spec_count": len(specs),
            "drafts_per_spec": per_spec,
            "draft_count": len(raw_candidates),
            "realize_failures": realize_failures,
            "empty_specs": max(0, len(specs) - len({str((d or {}).get("spec_id") or "").strip() for d in raw_candidates if isinstance(d, dict)})),
        },
        sample=_summarize_candidate_sample(raw_candidates[0]) if raw_candidates else None,
    )

    if not raw_candidates:
        return []

    # Stage: solver + ambiguity + judge + optional repair.
    accepted: List[dict] = []
    judge_floor = int(cfg.get("judge_pass_score") or DEFAULT_SEARCH_CONFIG["judge_pass_score"])
    judge_require_pass_flag = _as_bool(cfg.get("judge_require_pass_flag"), default=False)
    solver_consensus_n = max(1, min(int(cfg.get("solver_consensus_n") or 1), 3))
    answer_mismatch_penalty = max(0, int(cfg.get("answer_mismatch_penalty") or DEFAULT_SEARCH_CONFIG["answer_mismatch_penalty"]))
    ambiguity_penalty_score = max(0, int(cfg.get("ambiguity_penalty_score") or DEFAULT_SEARCH_CONFIG["ambiguity_penalty_score"]))
    max_repairs = max(0, int(cfg.get("max_repair_rounds") or 0))
    repair_band = max(0, int(cfg.get("repair_score_band") or DEFAULT_SEARCH_CONFIG["repair_score_band"]))
    repair_min_score = max(0, int(cfg.get("repair_min_score") or DEFAULT_SEARCH_CONFIG["repair_min_score"]))
    judged_total = 0
    repairs_attempted = 0
    reject_reason_counts: Dict[str, int] = {}

    def _bump_reject_reasons(reasons: List[str]) -> None:
        for reason in reasons:
            key = str(reason or "").strip()
            if not key:
                continue
            reject_reason_counts[key] = int(reject_reason_counts.get(key) or 0) + 1

    async def _solve_with_consensus(stem_text: str, solve_options: dict) -> dict:
        outcomes: List[dict] = []
        for _ in range(solver_consensus_n):
            try:
                result = await solve_draft(stem_text, solve_options)
            except Exception as exc:
                result = {
                    "match": False,
                    "final_answer": "",
                    "issues": [f"solver_exception:{str(exc)}"],
                    "summary": "",
                }
            outcomes.append(result if isinstance(result, dict) else {})

        true_votes = sum(1 for item in outcomes if bool(item.get("match")))
        target_match = true_votes * 2 >= len(outcomes) + 1

        combined_issues: List[str] = []
        best_result: dict = {}
        for item in outcomes:
            if not best_result and bool(item.get("match")) == target_match:
                best_result = dict(item)
            raw_issues = item.get("issues")
            if isinstance(raw_issues, list):
                for issue in raw_issues:
                    txt = str(issue or "").strip()
                    if txt:
                        combined_issues.append(txt)
        if not best_result and outcomes:
            best_result = dict(outcomes[0])

        return {
            "match": target_match,
            "final_answer": str(best_result.get("final_answer") or "").strip(),
            "issues": _clip_unique(combined_issues, 8),
            "summary": str(best_result.get("summary") or "").strip(),
            "match_votes": true_votes,
            "consensus_n": len(outcomes),
        }

    for cand in raw_candidates:
        if not isinstance(cand, dict):
            continue
        stem = str(cand.get("stem") or "").strip()
        ans = str(cand.get("answer") or "").strip()
        ana = str(cand.get("analysis") or "").strip()
        if not stem or not ans or not ana:
            continue

        # Find the matching spec (best-effort by spec_id).
        spec_id = str(cand.get("spec_id") or "").strip()
        spec = next((s for s in specs if isinstance(s, dict) and str(s.get("spec_id") or "").strip() == spec_id), {})  # type: ignore[assignment]
        if not isinstance(spec, dict):
            spec = {}

        attempt = 0
        current = dict(cand)
        while True:
            solved = await _solve_with_consensus(
                str(current.get("stem") or ""),
                {"subject": str(spec.get("subject") or ""), "proposed_answer": str(current.get("answer") or "")},
            )
            amb = await check_ambiguity(current)
            ambiguous_issues = [str(x or "").strip() for x in (amb.get("issues") or []) if str(x or "").strip()][:6]
            judge = await judge_draft(current, spec)
            judge = dict(judge or {})

            issues = list(judge.get("issues") or []) if isinstance(judge.get("issues"), list) else []
            judge_pass = bool(judge.get("pass"))
            overall = max(0, int(judge.get("overall_score") or 0))
            penalty_total = 0
            if not bool(solved.get("match")):
                penalty_total += answer_mismatch_penalty
                issues.append("answer_mismatch")
                solver_issues = solved.get("issues")
                if isinstance(solver_issues, list):
                    issues.extend([f"solver:{str(x or '').strip()}" for x in solver_issues if str(x or "").strip()])
            if bool(amb.get("ambiguous")):
                penalty_total += ambiguity_penalty_score
                issues.extend([f"ambiguous:{x}" for x in ambiguous_issues])
            if penalty_total > 0:
                overall = max(0, overall - penalty_total)

            judge["overall_score"] = overall
            judge["issues"] = _clip_unique([str(x or "").strip() for x in issues if str(x or "").strip()], 12)
            passed = overall >= judge_floor and (judge_pass if judge_require_pass_flag else True)
            judged_total += 1

            issues_list = list(judge.get("issues") or []) if isinstance(judge.get("issues"), list) else []
            normalized_reasons = [str(x or "").strip() for x in issues_list if str(x or "").strip()]
            if overall < judge_floor:
                normalized_reasons.append("judge_below_floor")
            if judge_require_pass_flag and not judge_pass:
                normalized_reasons.append("judge_pass_false")

            if passed:
                keep = dict(current)
                keep["judge"] = judge
                accepted.append(keep)
                await _emit_stage_event(
                    on_stage_event,
                    phase="judge",
                    label="判题筛选",
                    progress=min(90.0, 80.0 + (len(accepted) / max(1, len(raw_candidates))) * 10.0),
                    stats={
                        "evaluated": judged_total,
                        "accepted": len(accepted),
                        "rejected": max(0, judged_total - len(accepted)),
                        "pass_rate": round(len(accepted) / max(1, judged_total), 3),
                        "repairs_attempted": repairs_attempted,
                        "reject_reason_counts": dict(reject_reason_counts),
                        "latest_score": overall,
                    },
                    sample=_summarize_candidate_sample(current),
                )
                break

            _bump_reject_reasons(normalized_reasons)

            # Only attempt repair for fixable issues (answer mismatch / ambiguity)
            # or when the draft is close to the pass floor. This avoids "washing"
            # low-quality template questions via a rewrite.
            has_answer_mismatch = any(reason == "answer_mismatch" for reason in normalized_reasons)
            has_ambiguity = any(reason.startswith("ambiguous:") for reason in normalized_reasons)
            close_to_floor = overall >= repair_min_score and overall < judge_floor and (judge_floor - overall) <= repair_band
            can_repair = (
                attempt < max_repairs
                and overall >= repair_min_score
                and (has_answer_mismatch or has_ambiguity or close_to_floor)
            )

            await _emit_stage_event(
                on_stage_event,
                phase="judge",
                label="判题筛选",
                progress=min(90.0, 80.0 + (judged_total / max(1, len(raw_candidates))) * 10.0),
                stats={
                    "evaluated": judged_total,
                    "accepted": len(accepted),
                    "rejected": max(0, judged_total - len(accepted)),
                    "pass_rate": round(len(accepted) / max(1, judged_total), 3),
                    "repairs_attempted": repairs_attempted,
                    "reject_reason_counts": dict(reject_reason_counts),
                    "latest_score": overall,
                    "latest_can_repair": can_repair,
                },
                sample={
                    **_summarize_candidate_sample(current),
                    "judge_summary": str(judge.get("summary") or "").strip(),
                    "judge_issues": normalized_reasons[:6],
                    "ambiguity_issues": ambiguous_issues,
                },
            )

            if not can_repair:
                break

            current = await refine_draft(current, judge)
            repairs_attempted += 1
            attempt += 1

    if not accepted:
        return []

    # Rank by judge overall_score desc (fallback to spec score when missing).
    accepted.sort(key=lambda x: int(((x.get("judge") or {}) if isinstance(x.get("judge"), dict) else {}).get("overall_score") or 0), reverse=True)

    finals = select_final(accepted, count=count)
    await _emit_stage_event(
        on_stage_event,
        phase="final_selection",
        label="终选入围",
        progress=92.0,
        stats={
            "accepted_pool": len(accepted),
            "final_count": len(finals),
            "top_scores": [
                int(((item.get("judge") or {}) if isinstance(item.get("judge"), dict) else {}).get("overall_score") or 0)
                for item in finals[:4]
            ],
        },
        sample=_summarize_candidate_sample(finals[0]) if finals else None,
    )
    return finals
