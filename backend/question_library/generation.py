from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from backend.core.llm_client import chat_completion_text, is_llm_configured
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE

DEFAULT_SEARCH_CONFIG = {
    "preset": "balanced-creative",
    "depth": 4,
    "beam_width": 6,
    "expand_budget": 54,
    "skill_branch_factor": 3,
    "reasoning_branch_factor": 4,
    "trap_branch_factor": 2,
    "surface_branch_factor": 2,
    "difficulty_match_weight": 0.24,
    "novelty_weight": 0.24,
    "ambiguity_penalty": 0.26,
    "template_penalty": 0.16,
    "judge_pass_score": 80,
    "difficulty_tolerance": 0.22,
    "solver_consensus_n": 2,
    "max_repair_rounds": 1,
    "drafts_per_spec": 2,
}


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


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\\s*", "", raw).lstrip()
        raw = re.sub(r"\\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    candidate = raw[start : end + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def build_source_pack(study_markdown: str, subject: str, topic: str) -> dict:
    # First pass: keep it simple and deterministic; can be upgraded to a distilled pack later.
    return {
        "subject": str(subject or "").strip(),
        "topic": str(topic or "").strip(),
        "study_markdown": _clip(str(study_markdown or ""), 12000),
        "facts": [],
        "skills": [],
        "common_mistakes": [],
        "forbidden_patterns": [],
    }


def seed_root_specs(source_pack: dict, count: int, difficulty: str, question_type: str) -> List[dict]:
    subj = str((source_pack or {}).get("subject") or "").strip()
    top = str((source_pack or {}).get("topic") or "").strip()
    specs: List[dict] = []
    n = max(1, min(int(count or 1), 50))
    for i in range(n):
        specs.append(
            {
                "spec_id": f"spec_{i+1}",
                "subject": subj,
                "topic": top,
                "difficulty": str(difficulty or "").strip(),
                "question_type": str(question_type or "").strip(),
                "layer": "root",
            }
        )
    return specs


def expand_skill_layer(specs: List[dict], config: dict) -> List[dict]:
    # Skeleton: keep specs unchanged for now.
    _ = config
    return [dict(s) for s in (specs or []) if isinstance(s, dict)]


def expand_reasoning_layer(specs: List[dict], config: dict) -> List[dict]:
    _ = config
    return [dict(s) for s in (specs or []) if isinstance(s, dict)]


def expand_trap_layer(specs: List[dict], config: dict) -> List[dict]:
    _ = config
    return [dict(s) for s in (specs or []) if isinstance(s, dict)]


def expand_surface_layer(specs: List[dict], config: dict) -> List[dict]:
    _ = config
    return [dict(s) for s in (specs or []) if isinstance(s, dict)]


def score_spec(spec: dict, source_pack: dict, config: dict) -> dict:
    # Skeleton heuristic: prefer non-empty difficulty/question_type fields.
    _ = source_pack
    _ = config
    out = dict(spec or {})
    score = 50.0
    if str(out.get("difficulty") or "").strip():
        score += 20.0
    if str(out.get("question_type") or "").strip():
        score += 20.0
    out["score"] = float(score)
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

    payload = {
        "subject": subj,
        "topic": topic,
        "difficulty": difficulty,
        "question_type": qtype,
        "study_markdown": study_md,
        "count": n,
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

    text = await chat_completion_text(
        messages=[
            {
                "role": "system",
                "content": "你是资深高中教研员。请严格输出 JSON object，不要输出 Markdown，不要解释。",
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=float(LESSON_PLAN_TEMPERATURE),
        max_tokens=int(LESSON_PLAN_MAX_TOKENS),
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=3,
        req_id_prefix="qlg",
    )

    obj = _extract_json_obj(text)
    qs = obj.get("questions")
    if not isinstance(qs, list):
        return []

    out: List[dict] = []
    for q in qs:
        if not isinstance(q, dict):
            continue
        stem = str(q.get("stem") or "").strip()
        ans = str(q.get("answer") or "").strip()
        ana = str(q.get("analysis") or "").strip()
        if not stem or not ans or not ana:
            continue
        out.append({"stem": stem, "answer": ans, "analysis": ana})
        if len(out) >= n:
            break
    return out


async def solve_draft(stem: str, options: dict) -> dict:
    # Skeleton: trust draft output for now.
    _ = options
    return {"ok": True, "answer": "", "analysis": "", "stem": str(stem or "").strip()}


async def check_ambiguity(draft: dict) -> dict:
    _ = draft
    return {"ok": True, "issues": []}


async def judge_draft(draft: dict, spec: dict) -> dict:
    _ = spec
    # Skeleton: accept drafts that have answer + analysis.
    stem = str((draft or {}).get("stem") or "").strip()
    ans = str((draft or {}).get("answer") or "").strip()
    ana = str((draft or {}).get("analysis") or "").strip()
    ok = bool(stem and ans and ana)
    return {"pass": ok, "overall_score": 100 if ok else 0, "issues": [], "summary": ""}


async def refine_draft(draft: dict, judge: dict) -> dict:
    _ = judge
    return dict(draft or {})


def select_final(candidates: List[dict], count: int) -> List[dict]:
    n = max(1, min(int(count or 1), 20))
    out: List[dict] = []
    for c in candidates or []:
        if not isinstance(c, dict):
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
    config: Optional[dict] = None,
) -> List[dict]:
    cfg = dict(DEFAULT_SEARCH_CONFIG)
    if isinstance(config, dict):
        cfg.update(config)

    specs = seed_root_specs(source_pack, count=count, difficulty=difficulty, question_type=question_type)
    specs = expand_skill_layer(specs, cfg)
    specs = expand_reasoning_layer(specs, cfg)
    specs = expand_trap_layer(specs, cfg)
    specs = expand_surface_layer(specs, cfg)
    specs = [score_spec(s, source_pack, cfg) for s in specs]
    specs = beam_select(specs, cfg)

    drafts: List[dict] = []
    for spec in specs[: max(1, min(int(count or 1), 10))]:
        ds = await realize_drafts(spec, source_pack=source_pack, n=1)
        for d in ds:
            draft = dict(d)
            draft["spec_id"] = str(spec.get("spec_id") or "")
            drafts.append(draft)

    finals = select_final(drafts, count=count)
    return finals

