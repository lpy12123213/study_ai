"""AI 出题 benchmark 用例 schema：JSON 加载与校验。

用例是自包含的评分契约：除了出题请求参数（subject/topic/difficulty/
question_type/count），还携带确定性锚点——题干锚点（题目必须使用的给定数据）、
答案锚点（可验证的最终结果）、解析锚点（方法/步骤线索）与禁用模式
（常见错误答案）。锚点按生成契约把数值钉死在 topic 里，因此可以离线判定。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.generation.question_library.evolution_penalties import normalize_evolution_evaluation

VALID_DIFFICULTIES = ("基础", "中等", "困难", "压轴")
VALID_QUESTION_TYPES = ("选择题", "填空题", "解答题")

_CASES_DIR = Path(__file__).resolve().parent / "cases"


def default_cases_dir() -> Path:
    return _CASES_DIR


@dataclass
class QuestionCase:
    id: str
    title: str
    subject: str
    topic: str
    difficulty: str = "中等"
    question_type: str = "解答题"
    count: int = 3
    knowledge_points: List[str] = field(default_factory=list)
    stem_anchors: List[str] = field(default_factory=list)
    answer_anchors: List[str] = field(default_factory=list)
    analysis_anchors: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    min_stem_chars: int = 30
    min_analysis_chars: int = 80
    evolution_evaluation: Dict[str, Any] = field(default_factory=dict)

    def request_payload(self) -> Dict[str, Any]:
        """映射为 ``POST /api/question-library/generate`` 的请求体。"""
        return {
            "subject": self.subject,
            "topic": self.topic,
            "difficulty": self.difficulty,
            "question_type": self.question_type,
            "count": self.count,
            "knowledge_points": list(self.knowledge_points),
            "mode": "standard",
            # 基准不依赖本地学习归档，保证可复现；参考题检索保留为链路一部分。
            "use_study_archive": False,
            "use_reference_questions": True,
            "evolution_evaluation": dict(self.evolution_evaluation),
        }


class CaseValidationError(ValueError):
    pass


def _compile(pattern: str, *, case_id: str, where: str) -> str:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise CaseValidationError(f"case {case_id!r}: {where} 正则非法 {pattern!r}: {exc}") from exc
    return pattern


def parse_case(obj: Dict[str, Any], *, source: str = "") -> QuestionCase:
    if not isinstance(obj, dict):
        raise CaseValidationError(f"用例必须是 JSON 对象（{source or 'inline'}）")
    case_id = str(obj.get("id") or "").strip()
    if not case_id:
        raise CaseValidationError(f"用例缺少必填字段 id（{source or 'inline'}）")

    def _text(key: str) -> str:
        return str(obj.get(key) or "").strip()

    subject = _text("subject")
    topic = _text("topic")
    title = _text("title")
    if not title:
        raise CaseValidationError(f"case {case_id!r}: 缺少必填字段 title")
    if not subject:
        raise CaseValidationError(f"case {case_id!r}: 缺少必填字段 subject")
    if not topic:
        raise CaseValidationError(f"case {case_id!r}: 缺少必填字段 topic")

    difficulty = _text("difficulty") or "中等"
    if difficulty not in VALID_DIFFICULTIES:
        raise CaseValidationError(
            f"case {case_id!r}: difficulty 非法 {difficulty!r}，可选 {VALID_DIFFICULTIES}"
        )
    question_type = _text("question_type") or "解答题"
    if question_type not in VALID_QUESTION_TYPES:
        raise CaseValidationError(
            f"case {case_id!r}: question_type 非法 {question_type!r}，可选 {VALID_QUESTION_TYPES}"
        )

    try:
        raw_count = obj.get("count")
        count = 3 if raw_count is None else int(raw_count)
    except (TypeError, ValueError) as exc:
        raise CaseValidationError(f"case {case_id!r}: count 必须是整数") from exc
    if not 1 <= count <= 5:
        raise CaseValidationError(f"case {case_id!r}: count 必须在 1..5（单例出题请求的成本约束）")

    def _patterns(key: str) -> List[str]:
        raw = obj.get(key) or []
        if not isinstance(raw, list):
            raise CaseValidationError(f"case {case_id!r}: {key} 必须是数组")
        return [
            _compile(str(p), case_id=case_id, where=f"{key}[{i}]")
            for i, p in enumerate(raw)
            if str(p).strip()
        ]

    stem_anchors = _patterns("stem_anchors")
    answer_anchors = _patterns("answer_anchors")
    analysis_anchors = _patterns("analysis_anchors")
    forbidden = _patterns("forbidden_patterns")
    if not stem_anchors:
        raise CaseValidationError(f"case {case_id!r}: stem_anchors 不能为空（题目必须携带可判定的给定数据）")
    if not answer_anchors:
        raise CaseValidationError(f"case {case_id!r}: answer_anchors 不能为空（答案必须可确定性判定）")

    knowledge_points = [
        str(kp).strip()
        for kp in obj.get("knowledge_points") or []
        if str(kp).strip()
    ]
    if not knowledge_points:
        raise CaseValidationError(f"case {case_id!r}: knowledge_points 不能为空")

    return QuestionCase(
        id=case_id,
        title=title,
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        count=count,
        knowledge_points=knowledge_points,
        stem_anchors=stem_anchors,
        answer_anchors=answer_anchors,
        analysis_anchors=analysis_anchors,
        forbidden_patterns=forbidden,
        min_stem_chars=max(1, int(obj.get("min_stem_chars") or 30)),
        min_analysis_chars=max(1, int(obj.get("min_analysis_chars") or 80)),
        evolution_evaluation=normalize_evolution_evaluation(obj.get("evolution_evaluation")),
    )


def load_case_file(path: Any) -> List[QuestionCase]:
    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseValidationError(f"无法读取用例 {p}: {exc}") from exc
    if isinstance(obj, dict) and "cases" in obj:
        raw_cases = obj.get("cases") or []
        if not isinstance(raw_cases, list) or not raw_cases:
            raise CaseValidationError(f"用例包 {p}: cases 必须是非空数组")
        return [parse_case(raw, source=f"{p}#cases[{i}]") for i, raw in enumerate(raw_cases)]
    if not isinstance(obj, dict):
        raise CaseValidationError(f"用例必须是 JSON 对象: {p}")
    return [parse_case(obj, source=str(p))]


def load_case(path: Any) -> QuestionCase:
    cases = load_case_file(path)
    if len(cases) != 1:
        raise CaseValidationError(f"{Path(path)} 包含 {len(cases)} 个用例；请使用 load_case_file")
    return cases[0]


def load_cases(cases_dir: Optional[Any] = None) -> List[QuestionCase]:
    directory = Path(cases_dir) if cases_dir else default_cases_dir()
    if not directory.is_dir():
        raise CaseValidationError(f"用例目录不存在: {directory}")
    cases = [
        case
        for path in sorted(directory.glob("*.json"))
        for case in load_case_file(path)
    ]
    if not cases:
        raise CaseValidationError(f"用例目录为空: {directory}")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise CaseValidationError(f"用例 id 重复: {sorted(ids)}")
    return sorted(cases, key=lambda case: case.id)
