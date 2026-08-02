"""写作质量 rubric 诊断：W 维度（LLM 评审，独立诊断，不计入总分）。

``--llm-judge`` 启用时，由 LLM 按注册表 ``study.eval.rubric.v1`` 的 JSON 契约
对成稿的连贯性、文风、易错点真实性三个 0-5 子维度打分并各给一句理由。
结果只进成绩卡的独立 ``writing_rubric`` 字段用于报告展示：不进入百分制总分、
不影响四门槛与成熟度。judge 未启用/故障/输出非法时各子维度记 null 并记录
error，绝不抛异常击沉评分。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

# (system_prompt, markdown) -> LLM 原始输出（JSON 文本，或直接返回 dict）
LlmRubricJudge = Callable[[str, str], Any]

RUBRIC_PROMPT_ID = "study.eval.rubric.v1"

_SUBDIMENSIONS = ("coherence", "style", "misconception_authenticity")

# judge 输出被 ```json fence 整包时剥壳（真实运行 reflector 模型偶发 fence/散文输出）。
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(?P<body>.*?)```\s*$", re.S | re.I)
# 解析失败重试时的 user 消息提示；只重试一次。
_RETRY_HINT = "\n\n上次输出不是合法 JSON，请只输出 JSON 对象。"


def _null_w(error: str) -> Dict[str, Any]:
    return {
        "coherence": None,
        "style": None,
        "misconception_authenticity": None,
        "rationale": {},
        "error": error,
    }


def _clamp_score(value: Any) -> Optional[int]:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(5, score))


def _json_candidates(text: str) -> List[str]:
    """JSON 抽取容错序列：原文 → 剥 ```json fence → 首个 { 到末个 } 子串。"""

    candidates = [text]
    fenced = _CODE_FENCE_RE.match(text)
    if fenced:
        candidates.append(fenced.group("body").strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    return candidates


def _parse_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    saw_non_dict = False
    for candidate in _json_candidates(text):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
        saw_non_dict = True
    if saw_non_dict:
        raise ValueError("judge 输出不是 JSON 对象")
    raise ValueError("judge 未输出 JSON 对象")


def grade_rubric(markdown: str, *, judge_func: Optional[LlmRubricJudge] = None) -> Dict[str, Any]:
    """W 维度：LLM rubric 写作诊断。任何失败路径都记 null + error，不抛异常。"""
    if judge_func is None:
        return {"W": _null_w("judge_not_enabled")}
    if not str(markdown or "").strip():
        return {"W": _null_w("empty_markdown")}
    # 延迟导入：离线测试注入假 judge 时不触 LLM 栈（同 author/figures.py 模式）
    from backend.llm.prompts import create_default_prompt_registry

    system_prompt = create_default_prompt_registry().render(RUBRIC_PROMPT_ID).content
    try:
        raw = judge_func(system_prompt, markdown)
    except Exception as exc:  # noqa: BLE001 - judge 故障不得击沉评分
        return {"W": _null_w(f"judge_error: {exc}")}
    try:
        payload = _parse_payload(raw)
    except ValueError:
        # 解析失败重试一次：user 消息追加「只输出 JSON」提示；仍失败则记 parse_error + 原始输出前缀。
        try:
            raw = judge_func(system_prompt, f"{markdown}{_RETRY_HINT}")
        except Exception as exc:  # noqa: BLE001 - judge 故障不得击沉评分
            return {"W": _null_w(f"judge_error: {exc}")}
        try:
            payload = _parse_payload(raw)
        except ValueError as exc:
            return {"W": _null_w(f"parse_error: {exc} | raw: {str(raw or '')[:200]}")}

    rationale_raw = payload.get("rationale")
    rationale = rationale_raw if isinstance(rationale_raw, dict) else {}
    w: Dict[str, Any] = {name: _clamp_score(payload.get(name)) for name in _SUBDIMENSIONS}
    w["rationale"] = {name: str(rationale.get(name) or "") for name in _SUBDIMENSIONS}
    w["error"] = None
    return {"W": w}
