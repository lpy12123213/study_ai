"""Benchmark 用例 schema：JSON 加载与校验。

用例是自包含的评分契约：除了生成请求参数（query/subject/preset/options），
还携带评分锚点——期望知识点、事实检查点、陷阱（常见误解）、概念辨析对、
格式要求与权威来源域名。graders 只依赖本模块产出的 dataclass。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_PRESETS = ("quick", "standard", "deep", "research")

_CASES_DIR = Path(__file__).resolve().parent / "cases"


def default_cases_dir() -> Path:
    return _CASES_DIR


@dataclass
class FactMatch:
    """一条事实检查点的确定性匹配规则（对成稿 markdown 做正则）。

    通过条件：``all`` 全部命中；``any`` 非空时至少命中一条；``none`` 全部不命中。
    """

    all: List[str] = field(default_factory=list)
    any: List[str] = field(default_factory=list)
    none: List[str] = field(default_factory=list)


@dataclass
class RequiredFact:
    id: str
    description: str
    match: FactMatch
    source_urls: List[str] = field(default_factory=list)


@dataclass
class Trap:
    """常见误解陷阱：成稿把误解当事实陈述且未驳正时判 0 分。

    - ``wrong_pattern`` 命中且 ``correct_pattern`` 不命中 → 0（把误解写成了事实）
    - ``correct_pattern`` 命中 → 1（明确给出正确论断，无论是否点名误解）
    - 二者都不命中 → 0（未触及：用例指定的误解是合格讲义必须覆盖的）
    """

    id: str
    description: str
    wrong_pattern: str
    correct_pattern: str


@dataclass
class FormatRequirements:
    key_formulas: List[str] = field(default_factory=list)
    min_figures: int = 0
    min_tables: int = 0
    min_chars: int = 0


@dataclass
class BenchmarkCase:
    id: str
    title: str
    query: str
    subject: str = ""
    preset: str = "standard"
    requirements: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    expected_knowledge_points: List[str] = field(default_factory=list)
    min_unique_sources: int = 8
    expected_domains: List[str] = field(default_factory=list)
    required_facts: List[RequiredFact] = field(default_factory=list)
    traps: List[Trap] = field(default_factory=list)
    contrasts: List[List[str]] = field(default_factory=list)
    format_requirements: FormatRequirements = field(default_factory=FormatRequirements)

    def request_payload(self) -> Dict[str, Any]:
        """映射为 ``POST /api/study-materials/generate`` 的请求体。"""
        payload: Dict[str, Any] = {"query": self.query}
        if self.subject:
            payload["subject"] = self.subject
        if self.preset:
            payload["preset"] = self.preset
        if self.requirements:
            payload["requirements"] = self.requirements
        payload.update(self.options)
        return payload


class CaseValidationError(ValueError):
    pass


def _require_str(obj: Dict[str, Any], key: str, *, case_id: str) -> str:
    value = str(obj.get(key) or "").strip()
    if not value:
        raise CaseValidationError(f"case {case_id!r}: 缺少必填字段 {key!r}")
    return value


def _compile(pattern: str, *, case_id: str, where: str) -> str:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise CaseValidationError(f"case {case_id!r}: {where} 正则非法 {pattern!r}: {exc}") from exc
    return pattern


def _parse_fact(raw: Any, *, case_id: str, seen: set[str]) -> RequiredFact:
    if not isinstance(raw, dict):
        raise CaseValidationError(f"case {case_id!r}: required_facts 条目必须是对象")
    fact_id = _require_str(raw, "id", case_id=case_id)
    if fact_id in seen:
        raise CaseValidationError(f"case {case_id!r}: required_facts id 重复 {fact_id!r}")
    seen.add(fact_id)
    match_raw = raw.get("match") if isinstance(raw.get("match"), dict) else {}
    match = FactMatch(
        all=[_compile(str(p), case_id=case_id, where=f"fact {fact_id}.match.all") for p in match_raw.get("all") or []],
        any=[_compile(str(p), case_id=case_id, where=f"fact {fact_id}.match.any") for p in match_raw.get("any") or []],
        none=[_compile(str(p), case_id=case_id, where=f"fact {fact_id}.match.none") for p in match_raw.get("none") or []],
    )
    if not match.all and not match.any:
        raise CaseValidationError(f"case {case_id!r}: fact {fact_id!r} 必须至少有一条 match.all/any")
    return RequiredFact(
        id=fact_id,
        description=str(raw.get("description") or "").strip(),
        match=match,
        source_urls=[str(u).strip() for u in raw.get("source_urls") or [] if str(u).strip()],
    )


def _parse_trap(raw: Any, *, case_id: str, seen: set[str]) -> Trap:
    if not isinstance(raw, dict):
        raise CaseValidationError(f"case {case_id!r}: traps 条目必须是对象")
    trap_id = _require_str(raw, "id", case_id=case_id)
    if trap_id in seen:
        raise CaseValidationError(f"case {case_id!r}: traps id 重复 {trap_id!r}")
    seen.add(trap_id)
    return Trap(
        id=trap_id,
        description=str(raw.get("description") or "").strip(),
        wrong_pattern=_compile(_require_str(raw, "wrong_pattern", case_id=case_id), case_id=case_id, where=f"trap {trap_id}.wrong_pattern"),
        correct_pattern=_compile(_require_str(raw, "correct_pattern", case_id=case_id), case_id=case_id, where=f"trap {trap_id}.correct_pattern"),
    )


def parse_case(obj: Dict[str, Any], *, source: str = "") -> BenchmarkCase:
    if not isinstance(obj, dict):
        raise CaseValidationError(f"用例必须是 JSON 对象（{source or 'inline'}）")
    case_id = _require_str(obj, "id", case_id=source or "?")
    preset = str(obj.get("preset") or "standard").strip().lower() or "standard"
    if preset not in VALID_PRESETS:
        raise CaseValidationError(f"case {case_id!r}: preset 非法 {preset!r}，可选 {VALID_PRESETS}")

    fact_ids: set[str] = set()
    trap_ids: set[str] = set()
    facts = [_parse_fact(item, case_id=case_id, seen=fact_ids) for item in obj.get("required_facts") or []]
    traps = [_parse_trap(item, case_id=case_id, seen=trap_ids) for item in obj.get("traps") or []]
    if not facts:
        raise CaseValidationError(f"case {case_id!r}: required_facts 不能为空")

    fmt_raw = obj.get("format_requirements") if isinstance(obj.get("format_requirements"), dict) else {}
    fmt = FormatRequirements(
        key_formulas=[str(p) for p in fmt_raw.get("key_formulas") or []],
        min_figures=max(0, int(fmt_raw.get("min_figures") or 0)),
        min_tables=max(0, int(fmt_raw.get("min_tables") or 0)),
        min_chars=max(0, int(fmt_raw.get("min_chars") or 0)),
    )

    contrasts: List[List[str]] = []
    for pair in obj.get("contrasts") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise CaseValidationError(f"case {case_id!r}: contrasts 条目必须是二元数组")
        contrasts.append([str(pair[0]).strip(), str(pair[1]).strip()])

    options = obj.get("options") if isinstance(obj.get("options"), dict) else {}
    expected_kps = [str(kp).strip() for kp in obj.get("expected_knowledge_points") or [] if str(kp).strip()]
    if not expected_kps:
        raise CaseValidationError(f"case {case_id!r}: expected_knowledge_points 不能为空")

    return BenchmarkCase(
        id=case_id,
        title=_require_str(obj, "title", case_id=case_id),
        query=_require_str(obj, "query", case_id=case_id),
        subject=str(obj.get("subject") or "").strip(),
        preset=preset,
        requirements=str(obj.get("requirements") or "").strip(),
        options=dict(options),
        expected_knowledge_points=expected_kps,
        min_unique_sources=max(1, int(obj.get("min_unique_sources") or 1)),
        expected_domains=[str(d).strip().lower() for d in obj.get("expected_domains") or [] if str(d).strip()],
        required_facts=facts,
        traps=traps,
        contrasts=contrasts,
        format_requirements=fmt,
    )


def load_case(path: Any) -> BenchmarkCase:
    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseValidationError(f"无法读取用例 {p}: {exc}") from exc
    return parse_case(obj, source=str(p))


def load_cases(cases_dir: Optional[Any] = None) -> List[BenchmarkCase]:
    directory = Path(cases_dir) if cases_dir else default_cases_dir()
    if not directory.is_dir():
        raise CaseValidationError(f"用例目录不存在: {directory}")
    cases = [load_case(path) for path in sorted(directory.glob("*.json"))]
    if not cases:
        raise CaseValidationError(f"用例目录为空: {directory}")
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise CaseValidationError(f"用例 id 重复: {sorted(ids)}")
    return cases
