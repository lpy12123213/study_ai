from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.llm_client import chat_completion_text, is_llm_configured
from backend.core.settings import LESSON_PLAN_MAX_TOKENS, LESSON_PLAN_MODEL, LESSON_PLAN_TEMPERATURE
from backend.crawler_manager import get_crawler
from backend.database.models import get_question_cache, list_question_library_items

logger = get_logger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_CACHE_DIR = (_REPO_ROOT / ".local" / "reference_cache").resolve()

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
    "reference_alignment_weight": 0.12,
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
ReasoningEventHandler = Optional[Callable[[dict], Awaitable[None] | None]]
CandidateAcceptedHandler = Optional[Callable[[dict], Awaitable[None] | None]]
GenerationSnapshotHandler = Optional[Callable[[dict], Awaitable[None] | None]]


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


def _sample_unique(options: List[str], n: int) -> List[str]:
    deduped = _clip_unique(options, len(options or []))
    if not deduped:
        return []
    random.shuffle(deduped)
    return deduped[: max(1, int(n or 1))]


def _difficulty_rank(value: str) -> float:
    text = str(value or "").strip()
    if any(token in text for token in ["基础", "较易", "偏易", "简单", "易"]):
        return 0.0
    if any(token in text for token in ["中等", "适中"]):
        return 1.0
    if any(token in text for token in ["较难", "偏难", "困难", "压轴", "难"]):
        return 2.0
    return 1.0


def _difficulty_variants(target: str, n: int) -> List[str]:
    target_text = str(target or "").strip()
    rank = _difficulty_rank(target_text)
    total = max(1, int(n or 1))
    if rank <= 0.0:
        pool = ["基础", "简单", "简单", "中等", "简单"]
    elif rank >= 2.0:
        pool = ["偏难", "困难", "困难", "中等偏难", "困难"]
    else:
        pool = ["中等", "中等", "偏易", "偏难", "中等"]
    out: List[str] = []
    for index in range(total):
        out.append(pool[index % len(pool)])
    return out


def _difficulty_instruction(difficulty: str) -> str:
    rank = _difficulty_rank(difficulty)
    if rank <= 0.0:
        return "优先生成基础题，注重概念理解与基本方法，避免拔高为中高难综合题。"
    if rank >= 2.0:
        return "优先生成高难度题，注重思维深度、综合性与区分度，避免退化为基础套路题。"
    return "优先生成中等难度题，注重方法运用、常见变式和适度区分度。"


def _resolve_realize_temperature(difficulty: str) -> float:
    base = float(LESSON_PLAN_TEMPERATURE)
    rank = _difficulty_rank(difficulty)
    if rank <= 0.0:
        cap = 0.4
    elif rank >= 2.0:
        cap = 0.7
    else:
        cap = 0.55
    return max(0.1, min(cap, base if base > 0 else cap))


def _resolve_judge_model() -> str:
    raw = str(os.getenv("QUESTION_LIBRARY_JUDGE_MODEL") or "").strip()
    if raw:
        return raw
    return str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"


def _resolve_runtime_search_config(config: Optional[dict], *, count: int) -> dict:
    cfg = dict(DEFAULT_SEARCH_CONFIG)
    explicit = dict(config or {})
    cfg.update(explicit)

    target = max(1, min(int(count or 1), 10))
    if "beam_width" not in explicit:
        if target <= 3:
            cfg["beam_width"] = 6
        elif target >= 5:
            cfg["beam_width"] = 10
        else:
            cfg["beam_width"] = 8
    if "drafts_per_spec" not in explicit:
        cfg["drafts_per_spec"] = 2
    if "expand_budget" not in explicit:
        cfg["expand_budget"] = 60 if target <= 3 else 90 if target <= 5 else 120
    cfg["max_concurrent_realize"] = max(1, int(explicit.get("max_concurrent_realize") or 4))
    cfg["max_concurrent_judge"] = max(1, int(explicit.get("max_concurrent_judge") or 3))
    return cfg


def _difficulty_gap_ratio(target: str, estimated: str) -> float:
    if not str(target or "").strip() or not str(estimated or "").strip():
        return 0.0
    return min(1.0, abs(_difficulty_rank(target) - _difficulty_rank(estimated)) / 2.0)


def _difficulty_mismatch_penalty(target: str, estimated: str, tolerance: float) -> int:
    gap = _difficulty_gap_ratio(target, estimated)
    if gap <= max(0.0, float(tolerance or 0.0)):
        return 0
    if gap >= 0.9:
        return 20
    return 12


async def _emit_callback(handler: Optional[Callable[[dict], Awaitable[None] | None]], payload: dict) -> None:
    if handler is None:
        return
    try:
        result = handler(dict(payload))
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


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
    opts = _sample_unique(options, max_children)
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


async def _emit_reasoning_event(
    on_reasoning_event: ReasoningEventHandler,
    *,
    event_type: str,
    stage_id: str,
    stage_label: str,
    source: str = "",
    content: str = "",
    mode: str = "",
    message: str = "",
) -> None:
    if on_reasoning_event is None:
        return

    payload = {
        "type": str(event_type or "").strip() or "reasoning_delta",
        "stage_id": str(stage_id or "").strip(),
        "stage_label": str(stage_label or "").strip(),
    }
    if source:
        payload["source"] = str(source or "").strip()
    if content:
        payload["content"] = str(content or "").strip()
    if mode:
        payload["mode"] = str(mode or "").strip()
    if message:
        payload["message"] = str(message or "").strip()

    try:
        result = on_reasoning_event(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


async def _chat_json_with_reasoning(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    req_id_prefix: str,
    retries: int,
    raise_on_fail: bool,
    stage_id: str,
    stage_label: str,
    stream_reasoning: bool,
    on_reasoning_event: ReasoningEventHandler,
) -> str:
    emitted_chars = 0

    async def _on_reasoning_delta(chunk: str) -> None:
        nonlocal emitted_chars
        text = str(chunk or "")
        if not text.strip():
            return
        emitted_chars += len(text)
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_delta",
            stage_id=stage_id,
            stage_label=stage_label,
            source="raw",
            content=text,
        )

    if stream_reasoning:
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_status",
            stage_id=stage_id,
            stage_label=stage_label,
            mode="raw",
            message="尝试透传模型原始 reasoning。",
        )

    text = await chat_completion_text(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        reasoning={"effort": "medium", "exclude": not bool(stream_reasoning)},
        stream=bool(stream_reasoning),
        on_reasoning_delta=_on_reasoning_delta if stream_reasoning else None,
        raise_on_fail=raise_on_fail,
        retries=retries,
        req_id_prefix=req_id_prefix,
    )

    if stream_reasoning and emitted_chars <= 0:
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_status",
            stage_id=stage_id,
            stage_label=stage_label,
            mode="trace",
            message="当前模型未返回原始 reasoning，已降级为事件级 trace。",
        )
        await _emit_reasoning_event(
            on_reasoning_event,
            event_type="reasoning_delta",
            stage_id=stage_id,
            stage_label=stage_label,
            source="trace",
            content=f"{stage_label} 已完成一次模型调用。",
        )
    return text


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
    raw = str(os.getenv("QUESTION_LIBRARY_REALIZE_MAX_TOKENS") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except Exception:
            pass
    # 0 = unlimited (omit max_tokens from API payload)
    return 0


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
  
  
def _normalize_reference_source(value: Any) -> str:
      raw = str(value or "").strip().lower()
      if raw in {"gaokao", "高考", "exam"}:
          return "gaokao"
      if raw in {"mock", "模考", "模拟", "moni"}:
          return "mock"
      if raw in {"joint", "联考", "joint_exam"}:
          return "joint"
      return "any"


def _normalize_reference_year_range(value: Any) -> str:
      raw = str(value or "").strip().lower()
      if raw in {"3", "3y", "last3", "近3年"}:
          return "3"
      if raw in {"5", "5y", "last5", "近5年"}:
          return "5"
      return "all"


def _reference_source_label(value: Any) -> str:
      normalized = _normalize_reference_source(value)
      if normalized == "gaokao":
          return "高考真题"
      if normalized == "mock":
          return "模考题"
      if normalized == "joint":
          return "联考题"
      return "不限"


def _reference_year_range_label(value: Any) -> str:
      normalized = _normalize_reference_year_range(value)
      if normalized == "3":
          return "近3年"
      if normalized == "5":
          return "近5年"
      return "不限"


def _reference_source_token(value: Any) -> str:
      normalized = _normalize_reference_source(value)
      if normalized == "gaokao":
          return "高考"
      if normalized == "mock":
          return "模考"
      if normalized == "joint":
          return "联考"
      return ""


def _reference_year_threshold(value: Any) -> int:
      normalized = _normalize_reference_year_range(value)
      if normalized not in {"3", "5"}:
          return 0
      try:
          years = int(normalized)
      except Exception:
          return 0
      return max(0, time.localtime().tm_year - years + 1)


def _extract_reference_year(item: dict) -> int:
      if not isinstance(item, dict):
          return 0
      candidates = [
          str(item.get("date") or "").strip(),
          str(item.get("source") or "").strip(),
          str(item.get("url") or "").strip(),
      ]
      for candidate in candidates:
          if not candidate:
              continue
          match = re.search(r"(20\d{2})", candidate)
          if match:
              try:
                  return int(match.group(1))
              except Exception:
                  continue
      return 0


def _parse_knowledge_points_json(value: Any) -> List[str]:
      raw = value
      if isinstance(raw, str):
          text = raw.strip()
          if not text:
              return []
          try:
              raw = json.loads(text)
          except Exception:
              parts = [part.strip() for part in re.split(r"[，,;；、|/]+", text) if part.strip()]
              return _clip_unique(parts, 8)
      if isinstance(raw, list):
          return _clip_unique([str(item or "").strip() for item in raw if str(item or "").strip()], 8)
      return []


def _reference_query_candidates(topic: str, knowledge_points: List[str]) -> List[str]:
      out: List[str] = []
      topic_text = str(topic or "").strip()
      for item in knowledge_points or []:
          text = str(item or "").strip()
          if text:
              out.append(text[:48])
      if topic_text:
          first_line = topic_text.splitlines()[0].strip()
          if first_line:
              out.append(first_line[:60])
          normalized = re.sub(r"[，,;；|/]+", " ", first_line or topic_text)
          parts = [part.strip() for part in normalized.split() if part.strip()]
          if len(parts) > 1:
              out.extend(part[:32] for part in parts[:4])
      return _clip_unique(out, 5)


def _normalize_reference_question(item: dict, preview: Optional[dict] = None) -> Optional[dict]:
      if not isinstance(item, dict):
          return None
      preview_obj = preview if isinstance(preview, dict) else {}
      question_id = str(item.get("question_id") or preview_obj.get("question_id") or "").strip()
      stem = str(item.get("stem") or preview_obj.get("stem") or "").strip()
      if not question_id or not stem:
          return None
      source = str(item.get("source") or preview_obj.get("source") or "").strip()
      date = str(item.get("date") or preview_obj.get("date") or "").strip()
      knowledge_points = str(item.get("knowledge_points") or preview_obj.get("knowledge_points") or preview_obj.get("knowledge_point") or "").strip()
      question_type = str(item.get("question_type") or item.get("type") or preview_obj.get("question_type") or preview_obj.get("type") or "").strip()
      difficulty = str(item.get("difficulty") or preview_obj.get("difficulty") or "").strip()
      answer = str(item.get("answer") or preview_obj.get("answer") or "").strip()
      analysis = str(item.get("analysis") or preview_obj.get("analysis") or "").strip()
      return {
          "question_id": question_id,
          "stem": _clip(stem, 2400),
          "answer": _clip(answer, 2000),
          "analysis": _clip(analysis, 4000),
          "difficulty": difficulty,
          "question_type": question_type,
          "knowledge_points": knowledge_points,
          "source": source,
          "date": date,
          "url": str(item.get("url") or item.get("source_url") or preview_obj.get("url") or preview_obj.get("source_url") or "").strip(),
          "origin": str(item.get("origin") or preview_obj.get("origin") or "crawled").strip() or "crawled",
      }


def _reference_matches_constraints(item: dict, reference_source: str, reference_year_range: str) -> bool:
      if not isinstance(item, dict):
          return False
      source_token = _reference_source_token(reference_source)
      source_text = str(item.get("source") or "").strip()
      if source_token and source_text and source_token not in source_text:
          return False
      year_threshold = _reference_year_threshold(reference_year_range)
      if year_threshold > 0:
          year = _extract_reference_year(item)
          if year > 0 and year < year_threshold:
              return False
      return True


def _reference_cache_key(
      *,
      subject: str,
      topic: str,
      difficulty: str,
      question_type: str,
      knowledge_point_ids: List[str],
      knowledge_points: List[str],
      reference_source: str,
      reference_year_range: str,
  ) -> str:
      payload = {
          "subject": str(subject or "").strip(),
          "topic": str(topic or "").strip(),
          "difficulty": str(difficulty or "").strip(),
          "question_type": str(question_type or "").strip(),
          "knowledge_point_ids": [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()],
          "knowledge_points": [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()],
          "reference_source": _normalize_reference_source(reference_source),
          "reference_year_range": _normalize_reference_year_range(reference_year_range),
      }
      digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
      return digest[:24]


def _reference_cache_path(cache_key: str) -> Path:
      return (_REFERENCE_CACHE_DIR / f"{str(cache_key or '').strip()}.json").resolve()


def load_reference_cache(cache_key: str) -> Optional[dict]:
      key = str(cache_key or "").strip()
      if not key:
          return None
      path = _reference_cache_path(key)
      if not path.exists():
          return None
      try:
          raw = path.read_text(encoding="utf-8")
          obj = json.loads(raw) if raw else {}
      except Exception:
          return None
      if not isinstance(obj, dict):
          return None
      try:
          crawled_at_s = float(obj.get("crawled_at_s") or 0.0)
      except Exception:
          crawled_at_s = 0.0
      if crawled_at_s <= 0 or (time.time() - crawled_at_s) > 24 * 60 * 60:
          return None
      questions = []
      for item in obj.get("questions") or []:
          normalized = _normalize_reference_question(item if isinstance(item, dict) else {})
          if normalized is not None:
              questions.append(normalized)
      if not questions:
          return None
      return {
          "success": True,
          "source": "cache",
          "cache_hit": True,
          "degraded": False,
          "fallback_used": "",
          "error": "",
          "questions": questions,
          "count": len(questions),
      }


def save_reference_cache(cache_key: str, questions: List[dict]) -> Optional[dict]:
      key = str(cache_key or "").strip()
      if not key:
          return None
      normalized_questions = []
      for item in questions or []:
          normalized = _normalize_reference_question(item if isinstance(item, dict) else {})
          if normalized is not None:
              normalized_questions.append(normalized)
      if not normalized_questions:
          return None
      _REFERENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
      payload = {
          "cache_key": key,
          "crawled_at_s": time.time(),
          "questions": normalized_questions,
      }
      path = _reference_cache_path(key)
      path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
      return payload


async def collect_reference_questions(
      *,
      user_id: str,
      subject: str,
      topic: str,
      difficulty: str,
      question_type: str,
      knowledge_point_ids: Optional[List[str]] = None,
      knowledge_points: Optional[List[str]] = None,
      desired_count: int = 5,
      reference_source: str = "any",
      reference_year_range: str = "all",
  ) -> dict:
      kp_ids = [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()]
      kp_labels = [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()]
      target_count = max(5, min(10, int(desired_count or 5)))
      cache_key = _reference_cache_key(
          subject=subject,
          topic=topic,
          difficulty=difficulty,
          question_type=question_type,
          knowledge_point_ids=kp_ids,
          knowledge_points=kp_labels,
          reference_source=reference_source,
          reference_year_range=reference_year_range,
      )
      cached = load_reference_cache(cache_key)
      if isinstance(cached, dict) and cached.get("questions"):
          cached["trace"] = {"cache_key": cache_key, "queries": []}
          return cached

      queries = _reference_query_candidates(topic, kp_labels)
      source_token = _reference_source_token(reference_source)
      preview_by_id: Dict[str, dict] = {}
      crawler_errors: List[str] = []

      try:
          crawler = await get_crawler(subject=subject, strict=True)
          selected_ids: List[str] = []
          for query in queries:
              try:
                  search_result = await crawler.search_by_keyword(
                      keyword=query,
                      subject=subject,
                      difficulty=difficulty,
                      question_type=question_type,
                      limit=max(10, target_count * 2),
                      max_pages=2,
                      source_contains=source_token,
                      parse_content=False,
                  )
              except Exception as exc:
                  crawler_errors.append(str(exc))
                  continue
              candidates = search_result.get("questions") if isinstance(search_result, dict) else []
              if not isinstance(candidates, list):
                  candidates = []
              for candidate in candidates:
                  normalized_preview = _normalize_reference_question(candidate if isinstance(candidate, dict) else {})
                  if normalized_preview is None:
                      continue
                  if not _reference_matches_constraints(normalized_preview, reference_source, reference_year_range):
                      continue
                  qid = str(normalized_preview.get("question_id") or "").strip()
                  if not qid or qid in preview_by_id:
                      continue
                  preview_by_id[qid] = normalized_preview
                  selected_ids.append(qid)
                  if len(selected_ids) >= target_count:
                      break
              if len(selected_ids) >= target_count:
                  break

          if preview_by_id:
              details_result = await crawler.batch_get_question_details(list(preview_by_id.keys())[:target_count], max_concurrent=4)
              detail_items = details_result.get("questions") if isinstance(details_result, dict) else []
              if not isinstance(detail_items, list):
                  detail_items = []
              crawled_questions: List[dict] = []
              for detail in detail_items:
                  normalized = _normalize_reference_question(
                      detail if isinstance(detail, dict) else {},
                      preview_by_id.get(str((detail or {}).get("question_id") or "").strip()),
                  )
                  if normalized is None:
                      continue
                  if not _reference_matches_constraints(normalized, reference_source, reference_year_range):
                      continue
                  crawled_questions.append(normalized)
              if crawled_questions:
                  save_reference_cache(cache_key, crawled_questions)
                  return {
                      "success": True,
                      "source": "crawler",
                      "cache_hit": False,
                      "degraded": False,
                      "fallback_used": "",
                      "error": "",
                      "questions": crawled_questions[:target_count],
                      "count": len(crawled_questions[:target_count]),
                      "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
                  }
      except Exception as exc:
          crawler_errors.append(str(exc))

      local_candidates: List[tuple[int, dict]] = []
      if str(user_id or "").strip():
          try:
              local_batch = await list_question_library_items(
                  user_id=str(user_id or "").strip(),
                  subject=str(subject or "").strip(),
                  hidden="0",
                  limit=60,
                  offset=0,
                  sort="updated_at",
                  order="desc",
              )
          except Exception:
              local_batch = {}
          local_items = local_batch.get("items") if isinstance(local_batch, dict) else []
          if not isinstance(local_items, list):
              local_items = []
          topic_queries = _reference_query_candidates(topic, kp_labels)
          for item in local_items:
              if not isinstance(item, dict):
                  continue
              qid = str(item.get("question_id") or "").strip()
              if not qid:
                  continue
              source_text = str(item.get("source") or "").strip()
              date_text = str(item.get("date") or "").strip()
              normalized_meta = {
                  "question_id": qid,
                  "source": source_text,
                  "date": date_text,
              }
              if not _reference_matches_constraints(normalized_meta, reference_source, reference_year_range):
                  continue
              knowledge_candidates = [str(item.get("knowledge_point") or "").strip()]
              knowledge_candidates.extend(_parse_knowledge_points_json(item.get("knowledge_points_json")))
              stem_text = str(item.get("stem") or "").strip()
              score = 0
              if source_text:
                  score += 1
              if date_text:
                  score += 1
              if str(item.get("quality_score") or "").strip():
                  try:
                      score += max(0, min(5, int(item.get("quality_score") or 0) // 20))
                  except Exception:
                      score += 0
              for label in kp_labels[:6]:
                  if label and any(label in candidate for candidate in knowledge_candidates if candidate):
                      score += 3
              for query in topic_queries[:4]:
                  if query and (query in stem_text or any(query in candidate for candidate in knowledge_candidates if candidate)):
                      score += 2
              if score > 0:
                  local_candidates.append((score, dict(item)))
          local_candidates.sort(key=lambda pair: pair[0], reverse=True)
          local_ids = [str(item.get("question_id") or "").strip() for _, item in local_candidates[:target_count * 2]]
          local_ids = [item for item in local_ids if item]
          if local_ids:
              try:
                  cache_records = await get_question_cache(question_ids=local_ids)
              except Exception:
                  cache_records = {}
              normalized_local_questions: List[dict] = []
              for _, item in local_candidates[:target_count * 2]:
                  qid = str(item.get("question_id") or "").strip()
                  cache_record = cache_records.get(qid) if isinstance(cache_records, dict) else None
                  if not isinstance(cache_record, dict):
                      continue
                  normalized = _normalize_reference_question(
                      {
                          "question_id": qid,
                          "stem": cache_record.get("stem"),
                          "answer": cache_record.get("answer"),
                          "analysis": cache_record.get("analysis"),
                          "difficulty": cache_record.get("difficulty") or item.get("difficulty"),
                          "question_type": cache_record.get("question_type") or item.get("question_type"),
                          "knowledge_points": cache_record.get("knowledge_points_json") or cache_record.get("knowledge_point") or item.get("knowledge_points_json") or item.get("knowledge_point"),
                          "source": cache_record.get("source") or item.get("source") or "本地题库",
                          "date": cache_record.get("date") or item.get("date"),
                          "source_url": cache_record.get("source_url") or item.get("source_url"),
                          "origin": item.get("origin") or "local",
                      }
                  )
                  if normalized is None:
                      continue
                  normalized["url"] = str(cache_record.get("source_url") or item.get("source_url") or "").strip()
                  normalized_local_questions.append(normalized)
                  if len(normalized_local_questions) >= target_count:
                      break
              if normalized_local_questions:
                  return {
                      "success": True,
                      "source": "local_library",
                      "cache_hit": False,
                      "degraded": True,
                      "fallback_used": "local_library",
                      "error": crawler_errors[0] if crawler_errors else "reference_crawl_empty",
                      "questions": normalized_local_questions,
                      "count": len(normalized_local_questions),
                      "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
                  }

      return {
          "success": False,
          "source": "none",
          "cache_hit": False,
          "degraded": True,
          "fallback_used": "",
          "error": crawler_errors[0] if crawler_errors else "reference_crawl_empty",
          "questions": [],
          "count": 0,
          "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
      }


def _normalize_reference_example(item: dict) -> Optional[dict]:
      if not isinstance(item, dict):
          return None
      question_id = str(item.get("question_id") or item.get("id") or "").strip()
      stem = str(item.get("stem") or item.get("question") or "").strip()
      if not stem:
          return None
      return {
          "question_id": question_id,
          "source": str(item.get("source") or "").strip(),
          "why_selected": _clip(str(item.get("why_selected") or item.get("summary") or "").strip(), 120),
          "stem": _clip(stem, 260),
          "answer_style": _clip(str(item.get("answer_style") or item.get("answer") or "").strip(), 160),
          "analysis_style": _clip(str(item.get("analysis_style") or item.get("analysis") or "").strip(), 220),
      }


def _fallback_reference_analysis(topic: str, reference_questions: List[dict]) -> dict:
      patterns: List[str] = []
      difficulty_markers: List[str] = []
      innovative_angles: List[str] = []
      format_conventions: List[str] = []
      examples: List[dict] = []
      topic_text = str(topic or "").strip()
      for question in reference_questions[:5]:
          if not isinstance(question, dict):
              continue
          question_type = str(question.get("question_type") or "").strip()
          knowledge = str(question.get("knowledge_points") or topic_text or "").strip()
          difficulty = str(question.get("difficulty") or "").strip()
          source = str(question.get("source") or "").strip()
          if question_type or knowledge:
              patterns.append(f"围绕{knowledge or topic_text}设计{question_type or '综合'}设问，保持题干结构紧凑。")
          if difficulty:
              difficulty_markers.append(f"参考题整体难度以{difficulty}为主，常通过条件变化与多步推导拉开区分度。")
          if source:
              innovative_angles.append(f"可借鉴{source}中的设问切入角度，但需替换具体数值、情境与结论。")
          if question.get("answer") or question.get("analysis"):
              format_conventions.append("答案先给关键结论，再用解析补足必要推导与分类讨论。")
          normalized_example = _normalize_reference_example(
              {
                  "question_id": question.get("question_id"),
                  "source": source,
                  "why_selected": f"覆盖{knowledge or topic_text}的常见设问方式",
                  "stem": question.get("stem"),
                  "answer": question.get("answer"),
                  "analysis": question.get("analysis"),
              }
          )
          if normalized_example is not None:
              examples.append(normalized_example)
      patterns = _clip_unique(patterns + [
          f"围绕{topic_text or '目标知识点'}设置分层条件与递进式设问。",
          "优先采用真实试卷常见的多步推导、分类讨论或参数变化结构。",
          "避免直接套用教材例题表达，保持真题风格但不复刻原题。",
      ], 6)
      difficulty_markers = _clip_unique(difficulty_markers + [
          "难度标定以条件复杂度、运算量和是否需要分类讨论为主。",
          "高质量参考题通常在结论明确前要求先完成关键中间量或辅助量构造。",
      ], 6)
      innovative_angles = _clip_unique(innovative_angles + [
          "可从真实试卷中提炼设问顺序、条件组合和答案组织方式。",
          "允许在真题常考方向上做新的条件组合与场景迁移。",
      ], 6)
      format_conventions = _clip_unique(format_conventions + [
          "答案表述保持结论清晰，解析按关键步骤推进，不写多余点评。",
          "若有多问，解析需与题目顺序对应，并在必要处点明分类依据。",
      ], 6)
      examples = [example for example in examples if isinstance(example, dict)][:3]
      while len(examples) < 2 and reference_questions:
          question = reference_questions[len(examples) % len(reference_questions)]
          normalized_example = _normalize_reference_example(
              {
                  "question_id": question.get("question_id"),
                  "source": question.get("source"),
                  "why_selected": f"补充{topic_text or '目标知识点'}的代表性问法",
                  "stem": question.get("stem"),
                  "answer": question.get("answer"),
                  "analysis": question.get("analysis"),
              }
          )
          if normalized_example is None:
              break
          examples.append(normalized_example)
      return {
          "question_patterns": patterns[:6],
          "difficulty_markers": difficulty_markers[:6],
          "innovative_angles": innovative_angles[:6],
          "format_conventions": format_conventions[:6],
          "representative_examples": examples[:3],
      }


async def analyze_reference_questions(
      *,
      subject: str,
      topic: str,
      difficulty: str,
      question_type: str,
      reference_questions: List[dict],
      stream_reasoning: bool = False,
      on_reasoning_event: ReasoningEventHandler = None,
  ) -> dict:
      fallback = _fallback_reference_analysis(topic, reference_questions)
      if not is_llm_configured() or not reference_questions:
          return fallback

      payload = {
          "subject": str(subject or "").strip(),
          "topic": str(topic or "").strip(),
          "difficulty": str(difficulty or "").strip(),
          "question_type": str(question_type or "").strip(),
          "reference_questions": [
              {
                  "question_id": str((item or {}).get("question_id") or "").strip(),
                  "source": str((item or {}).get("source") or "").strip(),
                  "difficulty": str((item or {}).get("difficulty") or "").strip(),
                  "question_type": str((item or {}).get("question_type") or "").strip(),
                  "knowledge_points": str((item or {}).get("knowledge_points") or "").strip(),
                  "stem": _clip(str((item or {}).get("stem") or "").strip(), 260),
                  "answer": _clip(str((item or {}).get("answer") or "").strip(), 160),
                  "analysis": _clip(str((item or {}).get("analysis") or "").strip(), 240),
              }
              for item in (reference_questions or [])[:8]
              if isinstance(item, dict)
          ],
          "output_schema": {
              "question_patterns": "string[]",
              "difficulty_markers": "string[]",
              "innovative_angles": "string[]",
              "format_conventions": "string[]",
              "representative_examples": [
                  {
                      "question_id": "string",
                      "source": "string",
                      "why_selected": "string",
                      "stem": "string",
                      "answer_style": "string",
                      "analysis_style": "string",
                  }
              ],
          },
      }

      text = await _chat_json_with_reasoning(
          messages=[
              {
                  "role": "system",
                  "content": (
                      "<role>你是高考研究专家，负责从真题/模考题中提炼可复用的出题规律。</role>\n"
                      "<analysis_focus>\n"
                      "  <aspect>设问顺序与递进逻辑</aspect>\n"
                      "  <aspect>条件与结论的组合方式</aspect>\n"
                      "  <aspect>解题关键步骤分布</aspect>\n"
                      "  <aspect>答案格式规范</aspect>\n"
                      "</analysis_focus>\n"
                      "<field_guidelines>\n"
                      "  <field name='question_patterns'>题目设计规律，具体到设问结构，如【先求参数再讨论范围】</field>\n"
                      "  <field name='difficulty_markers'>难度来源，如【条件需要分类导致运算量增大】</field>\n"
                      "  <field name='innovative_angles'>创新切入点，可复用的新约束、新情境组合方式</field>\n"
                      "  <field name='format_conventions'>答案/解析格式规范，如【先给结论再写推导】</field>\n"
                      "  <field name='representative_examples'>最具代表性的2-3道题，含选题理由</field>\n"
                      "</field_guidelines>\n"
                      "<output_format>严格输出 JSON object，不输出解释或Markdown。</output_format>"
                  ),
              },
              {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
          ],
          model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
          temperature=0.2,
          max_tokens=0,
          req_id_prefix="ql_ref_analysis",
          retries=2,
          raise_on_fail=False,
          stage_id="reference_analysis",
          stage_label="参考题分析",
          stream_reasoning=stream_reasoning,
          on_reasoning_event=on_reasoning_event,
      )
      obj = _extract_json_obj(text)
      patterns = _clip_unique(
          [str(item or "").strip() for item in (obj.get("question_patterns") or []) if str(item or "").strip()]
          + list(fallback.get("question_patterns") or []),
          6,
      )
      difficulty_markers = _clip_unique(
          [str(item or "").strip() for item in (obj.get("difficulty_markers") or []) if str(item or "").strip()]
          + list(fallback.get("difficulty_markers") or []),
          6,
      )
      innovative_angles = _clip_unique(
          [str(item or "").strip() for item in (obj.get("innovative_angles") or []) if str(item or "").strip()]
          + list(fallback.get("innovative_angles") or []),
          6,
      )
      format_conventions = _clip_unique(
          [str(item or "").strip() for item in (obj.get("format_conventions") or []) if str(item or "").strip()]
          + list(fallback.get("format_conventions") or []),
          6,
      )
      examples: List[dict] = []
      for item in (obj.get("representative_examples") or []):
          normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
          if normalized is not None:
              examples.append(normalized)
      for item in fallback.get("representative_examples") or []:
          normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
          if normalized is not None:
              examples.append(normalized)
      deduped_examples: List[dict] = []
      seen_example_keys: set[str] = set()
      for example in examples:
          key = json.dumps({"question_id": example.get("question_id"), "stem": example.get("stem")}, ensure_ascii=False, sort_keys=True)
          if key in seen_example_keys:
              continue
          seen_example_keys.add(key)
          deduped_examples.append(example)
          if len(deduped_examples) >= 3:
              break
      return {
          "question_patterns": patterns[:6],
          "difficulty_markers": difficulty_markers[:6],
          "innovative_angles": innovative_angles[:6],
          "format_conventions": format_conventions[:6],
          "representative_examples": deduped_examples[:3],
      }


def enrich_source_pack_with_reference(source_pack: dict, reference_analysis: dict, reference_questions: List[dict]) -> dict:
      base = dict(source_pack or {})
      analysis = reference_analysis if isinstance(reference_analysis, dict) else {}
      examples = []
      for item in analysis.get("representative_examples") or []:
          normalized = _normalize_reference_example(item if isinstance(item, dict) else {})
          if normalized is not None:
              examples.append(normalized)
      if not examples:
          for item in (reference_questions or [])[:3]:
              normalized = _normalize_reference_example(
                  {
                      "question_id": str((item or {}).get("question_id") or "").strip(),
                      "source": str((item or {}).get("source") or "").strip(),
                      "why_selected": f"覆盖{str((item or {}).get('knowledge_points') or (base or {}).get('topic') or '').strip() or '目标知识点'}的代表性设问",
                      "stem": str((item or {}).get("stem") or "").strip(),
                      "answer": str((item or {}).get("answer") or "").strip(),
                      "analysis": str((item or {}).get("analysis") or "").strip(),
                  }
              )
              if normalized is None:
                  break
              examples.append(normalized)
      base["reference_patterns"] = _clip_unique(
          [str(item or "").strip() for item in (analysis.get("question_patterns") or []) if str(item or "").strip()]
          + [str(item or "").strip() for item in (analysis.get("innovative_angles") or []) if str(item or "").strip()],
          8,
      )
      base["reference_examples"] = examples[:3]
      base["difficulty_calibration"] = _clip_unique(
          [str(item or "").strip() for item in (analysis.get("difficulty_markers") or []) if str(item or "").strip()],
          6,
      )
      base["reference_format_conventions"] = _clip_unique(
          [str(item or "").strip() for item in (analysis.get("format_conventions") or []) if str(item or "").strip()],
          6,
      )
      base["reference_question_count"] = len([item for item in (reference_questions or []) if isinstance(item, dict)])
      base["reference_summary"] = "；".join((base.get("reference_patterns") or [])[:3])
      return base


async def build_source_pack(
      study_markdown: str,
      subject: str,
      topic: str,
      *,
      stream_reasoning: bool = False,
      on_reasoning_event: ReasoningEventHandler = None,
) -> dict:
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
        "reference_patterns": [],
        "reference_examples": [],
        "difficulty_calibration": [],
        "reference_format_conventions": [],
        "reference_question_count": 0,
        "reference_summary": "",
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

    text = await _chat_json_with_reasoning(
        messages=[
            {"role": "system", "content": (
                "<role>你是高中教研专家，负责从学习资料中提炼直接可用于出题的结构化要素。</role>\n"
                "<field_guidelines>\n"
                "  <field name='facts'>核心公式/定理/结论，每条可独立成为考点，≤20条</field>\n"
                "  <field name='skills'>能力考查点，如参数讨论、换元化简、分类讨论、反证法，≤15条，注重多样性</field>\n"
                "  <field name='common_mistakes'>学生常见误区，具体可操作，如【忽略定义域导致漏解】，≤10条</field>\n"
                "  <field name='forbidden_patterns'>模板化/低质量套路特征，如【已知求值直接代入】【只需单步计算】，≤10条</field>\n"
                "</field_guidelines>\n"
                "<requirement>提炼结果要具体、可操作，避免笼统概括。</requirement>\n"
                "<output_format>严格输出 JSON object。</output_format>"
            )},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="ql_distill",
        retries=2,
        raise_on_fail=False,
        stage_id="source_pack",
        stage_label="素材整理",
        stream_reasoning=stream_reasoning,
        on_reasoning_event=on_reasoning_event,
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
    difficulty_variants = _difficulty_variants(str(difficulty or "").strip(), len(seed_tags))
    for i, tag in enumerate(seed_tags):
        specs.append(
            {
                "spec_id": f"spec_{i + 1}",
                "subject": subj,
                "topic": top,
                "difficulty": difficulty_variants[i] if i < len(difficulty_variants) else str(difficulty or "").strip(),
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
    out = dict(spec or {})
    sp = source_pack or {}
    difficulty = str(out.get("difficulty") or "").strip()
    target_difficulty = str((config or {}).get("target_difficulty") or difficulty).strip()
    skill = str(out.get("skill") or "").strip()
    reasoning = str(out.get("reasoning") or "").strip()
    trap = str(out.get("trap") or "").strip()
    surface = str(out.get("surface") or "").strip()
    seed_tag = str(out.get("seed_tag") or "").strip()

    # Normalize sub-scores to [0, 1].
    difficulty_match = max(0.0, 1.0 - _difficulty_gap_ratio(target_difficulty, difficulty))

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

    reference_patterns = [str(item or "").strip() for item in (sp.get("reference_patterns") or []) if str(item or "").strip()]
    reference_examples = sp.get("reference_examples") if isinstance(sp.get("reference_examples"), list) else []
    has_reference = bool(reference_patterns or reference_examples)
    reference_blob = " ".join(
        reference_patterns
        + [str((item or {}).get("why_selected") or "").strip() for item in reference_examples if isinstance(item, dict)]
        + [str((item or {}).get("stem") or "").strip() for item in reference_examples if isinstance(item, dict)]
    )
    reference_alignment = 0.5 if has_reference else 0.0
    matched_reference = False
    for token in [seed_tag, skill, reasoning, surface]:
        token_text = str(token or "").strip()
        if token_text and token_text in reference_blob:
            reference_alignment += 0.12
            matched_reference = True
    for kw in ["分类", "参数", "构造", "反例", "综合", "变化", "探究", "多步"]:
        if kw in reference_blob and kw in (f"{seed_tag} {skill} {reasoning} {surface}"):
            reference_alignment += 0.05
            matched_reference = True
    if has_reference and not matched_reference:
        reference_alignment = max(0.2, reference_alignment - 0.15)
    reference_alignment = min(1.0, reference_alignment)

    w_diff = float((config or {}).get("difficulty_match_weight") or 0.24)
    w_novel = float((config or {}).get("novelty_weight") or 0.24)
    w_skill = float((config or {}).get("skill_coverage_weight") or 0.2)
    w_solv = float((config or {}).get("solvability_weight") or 0.2)
    w_amb = float((config or {}).get("ambiguity_penalty") or 0.26)
    w_tpl = float((config or {}).get("template_penalty") or 0.16)
    w_ref = float((config or {}).get("reference_alignment_weight") or DEFAULT_SEARCH_CONFIG["reference_alignment_weight"])

    score = (
        w_diff * difficulty_match
        + w_novel * novelty
        + w_skill * skill_coverage
        + w_solv * solvability
        + w_ref * reference_alignment
        - w_amb * ambiguity_risk
        - w_tpl * template_similarity
    )
    score += random.uniform(-0.05, 0.05)
    # Convert to a 0-100-ish scale for easier debugging.
    out["reference_alignment"] = round(reference_alignment, 4)
    out["score"] = float(max(0.0, min(1.0, score)) * 100.0 + reasoning_depth * 8.0)
    return out


def beam_select(specs: List[dict], config: dict) -> List[dict]:
    bw = max(1, int((config or {}).get("beam_width") or DEFAULT_SEARCH_CONFIG["beam_width"]))
    scored: List[dict] = []
    for s in specs or []:
        if isinstance(s, dict):
            scored.append(dict(s))
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

    buckets: dict[str, List[dict]] = {}
    for item in scored:
        key = str(item.get("seed_tag") or item.get("skill") or item.get("reasoning") or item.get("spec_id") or "").strip()
        key = key or "__default__"
        buckets.setdefault(key, []).append(item)

    ordered_keys = sorted(
        buckets.keys(),
        key=lambda key: float(((buckets.get(key) or [{}])[0]).get("score") or 0.0),
        reverse=True,
    )

    selected: List[dict] = []
    used_ids: set[str] = set()
    while len(selected) < bw:
        progressed = False
        for key in ordered_keys:
            bucket = buckets.get(key) or []
            while bucket:
                candidate = bucket.pop(0)
                spec_id = str(candidate.get("spec_id") or "").strip()
                if spec_id and spec_id in used_ids:
                    continue
                if spec_id:
                    used_ids.add(spec_id)
                selected.append(candidate)
                progressed = True
                break
            if len(selected) >= bw:
                break
        if not progressed:
            break

    if len(selected) < bw:
        for item in scored:
            spec_id = str(item.get("spec_id") or "").strip()
            if spec_id and spec_id in used_ids:
                continue
            if spec_id:
                used_ids.add(spec_id)
            selected.append(item)
            if len(selected) >= bw:
                break
    return selected[:bw]


async def realize_drafts(
    spec: dict,
    *,
    source_pack: dict,
    n: int = 2,
    stream_reasoning: bool = False,
    on_reasoning_event: ReasoningEventHandler = None,
) -> List[dict]:
    if not is_llm_configured():
        return []

    subj = str((spec or {}).get("subject") or (source_pack or {}).get("subject") or "").strip() or "高中数学"
    topic = str((spec or {}).get("topic") or (source_pack or {}).get("topic") or "").strip()
    difficulty = str((spec or {}).get("difficulty") or "").strip()
    qtype = str((spec or {}).get("question_type") or "").strip()
    study_md = str((source_pack or {}).get("study_markdown") or "").strip()
    n = max(1, min(int(n or 1), 4))

    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"
    temperature = _resolve_realize_temperature(difficulty)
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
                        "<retry_reason>上一次 JSON 可能截断或格式有误。</retry_reason>\n"
                        "<constraints>\n"
                        "  <rule>只输出 1 道题</rule>\n"
                        "  <rule>解析 ≤ 8 句短句</rule>\n"
                        "  <rule>禁止陷阱/易错/点评等元文本</rule>\n"
                        "  <rule>禁止重复题干内容</rule>\n"
                        "  <rule>若题目条件导致无解或矛盾，直接换一道合理可解的题目</rule>\n"
                        "</constraints>\n"
                        "<output_format>仅输出 JSON object，确保完整闭合。</output_format>"
                    ),
                },
                *messages,
            ]

        text = await _chat_json_with_reasoning(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            req_id_prefix="qlg",
            retries=3,
            raise_on_fail=True,
            stage_id="draft_realization",
            stage_label="草稿生成",
            stream_reasoning=stream_reasoning,
            on_reasoning_event=on_reasoning_event,
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
    reference_patterns = [str(x).strip() for x in (sp.get("reference_patterns") or []) if str(x or "").strip()]
    difficulty_calibration = [str(x).strip() for x in (sp.get("difficulty_calibration") or []) if str(x or "").strip()]
    reference_format_conventions = [str(x).strip() for x in (sp.get("reference_format_conventions") or []) if str(x or "").strip()]
    raw_reference_examples = sp.get("reference_examples") if isinstance(sp.get("reference_examples"), list) else []
    reference_examples = []
    for item in raw_reference_examples:
        if not isinstance(item, dict):
            continue
        reference_examples.append(
            {
                "question_id": str(item.get("question_id") or "").strip(),
                "source": str(item.get("source") or "").strip(),
                "why_selected": str(item.get("why_selected") or "").strip(),
                "stem": str(item.get("stem") or "").strip(),
                "answer_style": str(item.get("answer_style") or "").strip(),
                "analysis_style": str(item.get("analysis_style") or "").strip(),
            }
        )

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
            "reference_patterns": reference_patterns[:8],
            "difficulty_calibration": difficulty_calibration[:6],
            "format_conventions": reference_format_conventions[:6],
            "length_budget": {
                # Hard-ish caps to keep JSON responses small enough to be reliably
                # parseable (avoid max_tokens truncation), especially on verbose models.
                "max_sub_questions": 2,
                "stem_max_chars": 520,
                "answer_max_chars": 600,
                "analysis_max_chars": 1500,
            },
            "must_have": [
                "思维深度：多步推导/参数变化/分类讨论/构造/数形结合/反证法 至少满足其一",
                "区分度：不直接套单一公式，不是教材例题换皮，有新约束条件或知识点组合",
                "答案唯一确定：条件充分且不矛盾，推导可复现，结论明确",
                "LaTeX规范：行内\\(...\\)、独立\\[...\\]，严禁$...$，表格用array/cases",
            ],
        },
        "reference_examples": reference_examples[:3],
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
        "<role>你是资深高中教研员，兼具出题、解题与审题三重视角。</role>\n"
        "<output_format>严格输出 JSON object，禁止 Markdown 代码块或任何解释文字。</output_format>\n"
        "<latex_rules>\n"
        "  行内公式：\\(...\\)　独立公式：\\[...\\]\n"
        "  严禁 $...$\n"
        "  表格/矩阵/分布列/分类讨论：必须用 LaTeX array/matrix/cases，禁止纯文本竖排。\n"
        "  禁止图片公式、MathML、SVG。题干/答案/解析统一遵守上述规范。\n"
        "</latex_rules>\n"
        f"<difficulty>{_difficulty_instruction(difficulty)}</difficulty>\n"
        "<quality_standards>\n"
        "  每道题必须满足以下全部要求：\n"
        "  <thinking_depth>至少具备以下之一：多步推导、参数变化分析、分类讨论、构造辅助量、数形结合、反证法</thinking_depth>\n"
        "  <discrimination>不直接套单一公式；非教材例题换皮；有新约束条件或知识点组合</discrimination>\n"
        "  <innovation>可在经典知识点上引入参数探究、跨概念组合或情境迁移</innovation>\n"
        "  <length_limit>最多2小问；解析只写关键推导步骤，禁止输出陷阱提示、易错点评等元文本</length_limit>\n"
        "</quality_standards>\n"
        "<verification_process>\n"
        "  生成后必须执行以下步骤再输出：\n"
        "  <step id='1'>从头独立解题，逐步验证答案推导正确</step>\n"
        "  <step id='2'>检查题干条件：无矛盾、无冗余、有唯一解</step>\n"
        "  <step id='3'>确认解析结论与 answer 字段完全一致</step>\n"
        "  <on_error>验算发现错误则修正后输出；题目无解/矛盾/过繁则直接换题</on_error>\n"
        "</verification_process>\n"
        "<reference_learning>\n"
        "  若 reference_examples/reference_patterns 有内容：参考其设问顺序与解析格式。\n"
        "  严禁照抄原题原数值原结论。\n"
        "</reference_learning>\n"
        "<json_integrity>确保 JSON 完整闭合可解析，不输出任何截断内容。</json_integrity>"
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
        "<role>你是资深高中教研员，负责局部重写试题的指定部分（题干/答案/解析之一）。</role>\n"
        "<edit_principle>只重写 section_key 指定的字段，保持其他字段的知识点、难度与结论不变。</edit_principle>\n"
        "<latex_rules>\n"
        "  行内公式：\\(...\\)　独立公式：\\[...\\]　严禁 $...$\n"
        "  表格/矩阵/分类讨论：必须用 LaTeX array/matrix/cases，禁止纯文本竖排。\n"
        "</latex_rules>\n"
        "<verification>重写后验算答案正确性，确保推导无误、结论与其余部分完全一致。</verification>\n"
        "<output_format>严格输出 JSON object，不输出 Markdown 或解释。</output_format>"
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

    text = await _chat_json_with_reasoning(
        messages=messages,
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=float(LESSON_PLAN_TEMPERATURE),
        max_tokens=0,
        req_id_prefix="qlr",
        retries=3,
        raise_on_fail=False,
        stage_id="draft_realization",
        stage_label="草稿生成",
        stream_reasoning=False,
        on_reasoning_event=None,
    )

    obj = _extract_json_obj(text)
    content = str(obj.get("content") or "").strip()
    if content:
        return content

    fallback_key = str(section_key or "").strip()
    if fallback_key in {"stem", "answer", "analysis"}:
        return str(obj.get(fallback_key) or "").strip()
    return ""


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
                    "<role>你是严谨的理科解题专家，独立解题能力强，不受参考答案影响。</role>\n"
                    "<task>\n"
                    "  <phase id='1'>完全忽略参考答案，独立完整解题，写出关键推导步骤和最终答案。</phase>\n"
                    "  <phase id='2'>将你的答案与参考答案对比，判断结论是否等价。</phase>\n"
                    "</task>\n"
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
            {"role": "system", "content": (
                "<role>你是专业审题专家，专门识别导致答案不唯一的歧义问题。</role>\n"
                "<ambiguity_criteria>\n"
                "  <rule>仅当题干条件允许多种合理解读且导致不同结论时，判定 ambiguous=true。</rule>\n"
                "  <not_ambiguous>分类讨论本身不是歧义</not_ambiguous>\n"
                "  <not_ambiguous>参数范围讨论不是歧义</not_ambiguous>\n"
                "  <is_ambiguous>无法从题干确定唯一答案路径时才标记 ambiguous=true</is_ambiguous>\n"
                "</ambiguity_criteria>\n"
                "<output_format>严格输出 JSON object。</output_format>"
            )},
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

    text = await _chat_json_with_reasoning(
        messages=[
            {
                "role": "system",
                "content": (
                    "<role>你是资深高中教研员，按高考评审标准鉴别试题质量，评分客观准确。</role>\n"
                    "<scoring_dimensions>\n"
                    "  <dim name='思维含量'>是否需要多步推理或策略选择，非机械套公式</dim>\n"
                    "  <dim name='区分度'>能否区分不同层次学生，非教材例题换皮</dim>\n"
                    "  <dim name='知识覆盖'>核心概念运用深度，考查角度是否有价值</dim>\n"
                    "  <dim name='表述规范'>题干清晰，LaTeX正确，条件充分无歧义</dim>\n"
                    "  <dim name='创新性'>非教材直接例题，有新约束条件或概念组合</dim>\n"
                    "  <dim name='答案解析自洽'>推导每步正确，结论与答案字段完全一致</dim>\n"
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


def select_final(candidates: List[dict], count: int) -> List[dict]:
    n = max(1, min(int(count or 1), 20))
    out: List[dict] = []
    seen: set[str] = set()
    combo_used: set[tuple[str, str, str]] = set()

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

        combo = (
            str(c.get("skill") or "").strip(),
            str(c.get("reasoning") or "").strip(),
            str(c.get("surface") or "").strip(),
        )
        if any(combo) and combo in combo_used and len(out) < n:
            continue
        if any(combo):
            combo_used.add(combo)

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
    on_reasoning_event: ReasoningEventHandler = None,
    on_candidate_accepted: CandidateAcceptedHandler = None,
    on_generation_snapshot: GenerationSnapshotHandler = None,
    stream_reasoning: bool = False,
    config: Optional[dict] = None,
) -> List[dict]:
    cfg = _resolve_runtime_search_config(config, count=count)
    cfg["target_difficulty"] = str(difficulty or "").strip()

    # Ensure source_pack contains distilled guidance for novelty/template avoidance.
    if not isinstance(source_pack, dict):
        source_pack = {}
    if not source_pack.get("skills") and not source_pack.get("forbidden_patterns"):
        try:
            source_pack = await build_source_pack(
                str(source_pack.get("study_markdown") or ""),
                str(source_pack.get("subject") or ""),
                str(source_pack.get("topic") or ""),
                stream_reasoning=stream_reasoning,
                on_reasoning_event=on_reasoning_event,
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
    realize_sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrent_realize") or 4)))

    async def _realize_spec(spec: dict) -> tuple[list[dict], Optional[Exception]]:
        async with realize_sem:
            try:
                ds = await realize_drafts(
                    spec,
                    source_pack=source_pack,
                    n=per_spec,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                out = [dict(item) for item in (ds or []) if isinstance(item, dict)]
                return out, None
            except Exception as exc:
                return [], exc

    realize_results = await asyncio.gather(*[_realize_spec(spec) for spec in specs]) if specs else []
    for spec, (drafts, error) in zip(specs, realize_results):
        if error is not None:
            realize_failures += 1
            logger.warning(
                "question_library_realize_drafts_failed",
                extra={
                    "spec_id": str((spec or {}).get("spec_id") or "").strip(),
                    "topic": str((spec or {}).get("topic") or "").strip(),
                    "error": str(error),
                },
            )
            continue
        raw_candidates.extend(drafts)

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
    await _emit_callback(
        on_generation_snapshot,
        {
            "phase": "draft_realization",
            "raw_candidates": [dict(item) for item in raw_candidates],
            "accepted": [],
            "stats": {"draft_count": len(raw_candidates), "realize_failures": realize_failures},
        },
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
    difficulty_tolerance = float(cfg.get("difficulty_tolerance") or DEFAULT_SEARCH_CONFIG["difficulty_tolerance"])
    judge_sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrent_judge") or 3)))

    def _bump_reject_reasons(reasons: List[str]) -> None:
        for reason in reasons:
            key = str(reason or "").strip()
            if not key:
                continue
            reject_reason_counts[key] = int(reject_reason_counts.get(key) or 0) + 1

    async def _solve_with_consensus(stem_text: str, solve_options: dict) -> dict:
        async def _run_solve() -> dict:
            try:
                result = await solve_draft(
                    stem_text,
                    solve_options,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
            except Exception as exc:
                result = {
                    "match": False,
                    "final_answer": "",
                    "issues": [f"solver_exception:{str(exc)}"],
                    "summary": "",
                }
            return result if isinstance(result, dict) else {}

        outcomes = await asyncio.gather(*[_run_solve() for _ in range(solver_consensus_n)])

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

    async def _evaluate_candidate(cand: dict) -> dict:
        async with judge_sem:
            if not isinstance(cand, dict):
                return {"accepted": False, "skip": True, "reasons": []}
            stem = str(cand.get("stem") or "").strip()
            ans = str(cand.get("answer") or "").strip()
            ana = str(cand.get("analysis") or "").strip()
            if not stem or not ans or not ana:
                return {"accepted": False, "skip": True, "reasons": []}

            spec_id = str(cand.get("spec_id") or "").strip()
            spec = next((s for s in specs if isinstance(s, dict) and str(s.get("spec_id") or "").strip() == spec_id), {})
            if not isinstance(spec, dict):
                spec = {}

            attempt = 0
            current = dict(cand)
            local_repairs = 0
            while True:
                solved_result, amb_result = await asyncio.gather(
                    _solve_with_consensus(
                        str(current.get("stem") or ""),
                        {"subject": str(spec.get("subject") or ""), "proposed_answer": str(current.get("answer") or "")},
                    ),
                    check_ambiguity(
                        current,
                        stream_reasoning=stream_reasoning,
                        on_reasoning_event=on_reasoning_event,
                    ),
                    return_exceptions=True,
                )
                if isinstance(solved_result, Exception):
                    solved = {"match": False, "final_answer": "", "issues": [f"solver_exception:{str(solved_result)}"], "summary": ""}
                else:
                    solved = dict(solved_result or {})
                if isinstance(amb_result, Exception):
                    amb = {"ambiguous": True, "issues": [f"ambiguity_exception:{str(amb_result)}"], "summary": ""}
                else:
                    amb = dict(amb_result or {})

                judge_result = await judge_draft(
                    current,
                    spec,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                judge = dict(judge_result or {})
                ambiguous_issues = [str(x or "").strip() for x in (amb.get("issues") or []) if str(x or "").strip()][:6]

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
                difficulty_penalty = _difficulty_mismatch_penalty(
                    str(difficulty or "").strip(),
                    str(judge.get("difficulty_estimate") or "").strip(),
                    difficulty_tolerance,
                )
                if difficulty_penalty > 0:
                    penalty_total += difficulty_penalty
                    issues.append("difficulty_mismatch")
                if penalty_total > 0:
                    overall = max(0, overall - penalty_total)

                judge["overall_score"] = overall
                judge["issues"] = _clip_unique([str(x or "").strip() for x in issues if str(x or "").strip()], 12)
                passed = overall >= judge_floor and (judge_pass if judge_require_pass_flag else True)

                issues_list = list(judge.get("issues") or []) if isinstance(judge.get("issues"), list) else []
                normalized_reasons = [str(x or "").strip() for x in issues_list if str(x or "").strip()]
                if overall < judge_floor:
                    normalized_reasons.append("judge_below_floor")
                if judge_require_pass_flag and not judge_pass:
                    normalized_reasons.append("judge_pass_false")

                if passed:
                    keep = dict(current)
                    keep["judge"] = judge
                    return {
                        "accepted": True,
                        "candidate": keep,
                        "score": overall,
                        "reasons": [],
                        "repairs_attempted": local_repairs,
                        "sample": _summarize_candidate_sample(current),
                    }

                has_answer_mismatch = any(reason == "answer_mismatch" for reason in normalized_reasons)
                has_ambiguity = any(reason.startswith("ambiguous:") for reason in normalized_reasons)
                has_difficulty_mismatch = any(reason == "difficulty_mismatch" for reason in normalized_reasons)
                close_to_floor = overall >= repair_min_score and overall < judge_floor and (judge_floor - overall) <= repair_band
                can_repair = (
                    attempt < max_repairs
                    and overall >= repair_min_score
                    and not has_difficulty_mismatch
                    and (has_answer_mismatch or has_ambiguity or close_to_floor)
                )

                if not can_repair:
                    return {
                        "accepted": False,
                        "candidate": dict(current),
                        "score": overall,
                        "reasons": normalized_reasons,
                        "repairs_attempted": local_repairs,
                        "sample": {
                            **_summarize_candidate_sample(current),
                            "judge_summary": str(judge.get("summary") or "").strip(),
                            "judge_issues": normalized_reasons[:6],
                            "ambiguity_issues": ambiguous_issues,
                        },
                    }

                current = await refine_draft(
                    current,
                    judge,
                    stream_reasoning=stream_reasoning,
                    on_reasoning_event=on_reasoning_event,
                )
                local_repairs += 1
                attempt += 1

    judge_tasks = [asyncio.create_task(_evaluate_candidate(cand)) for cand in raw_candidates if isinstance(cand, dict)]
    for future in asyncio.as_completed(judge_tasks):
        result = await future
        if result.get("skip"):
            continue
        judged_total += 1
        repairs_attempted += int(result.get("repairs_attempted") or 0)
        if bool(result.get("accepted")) and isinstance(result.get("candidate"), dict):
            keep = dict(result.get("candidate") or {})
            accepted.append(keep)
            await _emit_callback(on_candidate_accepted, keep)
        else:
            _bump_reject_reasons([str(x or "").strip() for x in (result.get("reasons") or []) if str(x or "").strip()])

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
                "latest_score": int(result.get("score") or 0),
            },
            sample=result.get("sample") if isinstance(result.get("sample"), dict) else None,
        )
        await _emit_callback(
            on_generation_snapshot,
            {
                "phase": "judge",
                "raw_candidates": [dict(item) for item in raw_candidates],
                "accepted": [dict(item) for item in accepted],
                "stats": {
                    "evaluated": judged_total,
                    "accepted": len(accepted),
                    "rejected": max(0, judged_total - len(accepted)),
                },
            },
        )

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
