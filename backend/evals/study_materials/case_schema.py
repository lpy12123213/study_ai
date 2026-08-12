"""Benchmark 用例 schema：JSON 加载与校验。

用例是自包含的评分契约：除了生成请求参数（query/subject/preset/options），
还携带评分锚点——期望知识点、事实检查点、陷阱（常见误解）、概念辨析对、
学习闭环、格式要求与权威来源域名。graders 只依赖本模块产出的 dataclass。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_PRESETS = ("quick", "standard", "deep", "research")
VALID_TIERS = ("smoke", "core", "extended")
VALID_CURRICULUM_SCOPES = ("", "high_school", "high_school_plus")
CASE_PACK_VERSION = 1

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
class LearningRequirements:
    """学习闭环的确定性门槛；标签由 ``benchmark_output_contract`` 约定。"""

    min_objectives: int = 3
    min_worked_examples: int = 2
    min_practice_questions: int = 6
    min_answered_questions: int = 6
    required_levels: List[str] = field(default_factory=lambda: ["基础", "应用", "迁移"])


def benchmark_output_contract(
    learning: Optional[LearningRequirements] = None,
    *,
    curriculum_scope: str = "",
    extension_topics: Optional[List[str]] = None,
    min_knowledge_sections: int = 0,
) -> str:
    """按用例门槛生成请求侧输出协议，避免评分要求与生成提示脱节。"""

    req = learning or LearningRequirements()
    levels = "".join(f"[{level}]" for level in req.required_levels)
    contract = (
        "评测输出契约：须含学习目标、前置知识、自测题、答案与评分点、参考文献；"
        f"列出至少{req.min_objectives}个可检验学习目标；"
        f"至少{req.min_worked_examples}个带完整步骤的例题，标为[EX1]起；"
        f"至少{req.min_practice_questions}道自测题，标为[Q1]起并覆盖{levels}，"
        f"答案标为[A1]起且至少{req.min_answered_questions}份一一对应并给评分点；"
        "关键事实句后用[^n]内联引文，文末脚注列标题与URL；明确边界条件、误区和反例。"
    )
    if min_knowledge_sections > 0:
        contract += f"；正文须以至少{int(min_knowledge_sections)}个独立知识点二级标题展开。"
    if curriculum_scope == "high_school":
        contract += "；内容与解法严格限定在高中课程范围，不引入大学专业知识作为作答前提。"
    elif curriculum_scope == "high_school_plus":
        topics = "、".join(extension_topics or [])
        contract += (
            f"；主题主线与作答前提限高中；允许拓展仅限{topics}。"
            "每项须用[拓展:上列对应主题全名]逐项标记，从高中知识推导，并紧跟[高中连接]说明其对高中"
            "解题、实验或材料分析的帮助；不得作为前置知识。"
        )
    return contract


# 默认协议保留为公共常量，供旧用例和外部调用方兼容使用。
BENCHMARK_OUTPUT_CONTRACT = benchmark_output_contract()


@dataclass
class BenchmarkCase:
    id: str
    title: str
    query: str
    tier: str = "core"
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
    learning_requirements: LearningRequirements = field(default_factory=LearningRequirements)
    curriculum_scope: str = ""
    extension_topics: List[str] = field(default_factory=list)

    @property
    def min_knowledge_sections(self) -> int:
        """G0 requires 80% of expected knowledge points to be learner-visible sections."""

        return max(1, (len(self.expected_knowledge_points) * 4 + 4) // 5)

    def request_payload(self) -> Dict[str, Any]:
        """映射为 ``POST /api/study-materials/generate`` 的请求体。"""
        payload: Dict[str, Any] = {"query": self.query}
        if self.subject:
            payload["subject"] = self.subject
        if self.preset:
            payload["preset"] = self.preset
        payload.update(self.options)
        # smoke/light 保持完整难度与评分协议，只压缩昂贵的补充百科和网页深读调用。
        if self.tier == "smoke":
            payload.setdefault("research_budget", "lean")
        requirements = benchmark_output_contract(
            self.learning_requirements,
            curriculum_scope=self.curriculum_scope,
            extension_topics=self.extension_topics,
            min_knowledge_sections=self.min_knowledge_sections,
        )
        if self.requirements:
            requirements += f"；主题附加要求：{self.requirements}"
        payload["requirements"] = requirements
        # 学习闭环是 challenge v2 的核心用户价值，不能被旧用例的 false 静默关闭。
        payload["with_questions"] = True
        # 基准必须真实跑生成，不能被本地历史归档短路。
        payload["prefer_local_archive"] = False
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
    source_urls = [str(url).strip() for url in raw.get("source_urls") or [] if str(url).strip()]
    if not source_urls:
        raise CaseValidationError(f"case {case_id!r}: fact {fact_id!r} 必须至少配置一个 source_url")
    invalid_urls = [url for url in source_urls if not re.match(r"^https?://", url, re.IGNORECASE)]
    if invalid_urls:
        raise CaseValidationError(
            f"case {case_id!r}: fact {fact_id!r} source_url 必须是 HTTP(S): {invalid_urls}"
        )
    return RequiredFact(
        id=fact_id,
        description=str(raw.get("description") or "").strip(),
        match=match,
        source_urls=source_urls,
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
    tier = str(obj.get("tier") or "core").strip().lower() or "core"
    if tier not in VALID_TIERS:
        raise CaseValidationError(f"case {case_id!r}: tier 非法 {tier!r}，可选 {VALID_TIERS}")
    curriculum_scope = str(obj.get("curriculum_scope") or "").strip().lower()
    if curriculum_scope not in VALID_CURRICULUM_SCOPES:
        raise CaseValidationError(
            f"case {case_id!r}: curriculum_scope 非法 {curriculum_scope!r}，可选 {VALID_CURRICULUM_SCOPES}"
        )
    extension_raw = obj.get("extension_topics") or []
    if not isinstance(extension_raw, list):
        raise CaseValidationError(f"case {case_id!r}: extension_topics 必须是数组")
    extension_topics = [
        str(topic).strip()
        for topic in extension_raw
        if str(topic).strip()
    ]
    if len(extension_topics) != len(set(extension_topics)):
        raise CaseValidationError(f"case {case_id!r}: extension_topics 不能重复")
    if len(extension_topics) > 3:
        raise CaseValidationError(f"case {case_id!r}: extension_topics 最多配置 3 项")
    if curriculum_scope == "high_school_plus" and not extension_topics:
        raise CaseValidationError(
            f"case {case_id!r}: high_school_plus 必须声明 extension_topics"
        )
    if curriculum_scope != "high_school_plus" and extension_topics:
        raise CaseValidationError(
            f"case {case_id!r}: extension_topics 仅用于 high_school_plus"
        )

    fact_ids: set[str] = set()
    trap_ids: set[str] = set()
    facts = [_parse_fact(item, case_id=case_id, seen=fact_ids) for item in obj.get("required_facts") or []]
    traps = [_parse_trap(item, case_id=case_id, seen=trap_ids) for item in obj.get("traps") or []]
    if not facts:
        raise CaseValidationError(f"case {case_id!r}: required_facts 不能为空")
    if not traps:
        raise CaseValidationError(f"case {case_id!r}: traps 不能为空")

    fmt_raw = obj.get("format_requirements") if isinstance(obj.get("format_requirements"), dict) else {}
    fmt = FormatRequirements(
        key_formulas=[str(p) for p in fmt_raw.get("key_formulas") or []],
        min_figures=max(0, int(fmt_raw.get("min_figures") or 0)),
        min_tables=max(0, int(fmt_raw.get("min_tables") or 0)),
        min_chars=max(0, int(fmt_raw.get("min_chars") or 0)),
    )

    learning_raw = obj.get("learning_requirements") if isinstance(obj.get("learning_requirements"), dict) else {}
    learning = LearningRequirements(
        min_objectives=max(1, int(learning_raw.get("min_objectives") or 3)),
        min_worked_examples=max(1, int(learning_raw.get("min_worked_examples") or 2)),
        min_practice_questions=max(1, int(learning_raw.get("min_practice_questions") or 6)),
        min_answered_questions=max(1, int(learning_raw.get("min_answered_questions") or 6)),
        required_levels=[
            str(level).strip()
            for level in learning_raw.get("required_levels") or ["基础", "应用", "迁移"]
            if str(level).strip()
        ],
    )
    if learning.min_answered_questions > learning.min_practice_questions:
        raise CaseValidationError(
            f"case {case_id!r}: min_answered_questions 不能大于 min_practice_questions"
        )
    if not learning.required_levels:
        raise CaseValidationError(f"case {case_id!r}: learning_requirements.required_levels 不能为空")

    contrasts: List[List[str]] = []
    for pair in obj.get("contrasts") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise CaseValidationError(f"case {case_id!r}: contrasts 条目必须是二元数组")
        contrasts.append([str(pair[0]).strip(), str(pair[1]).strip()])
    if not contrasts:
        raise CaseValidationError(f"case {case_id!r}: contrasts 不能为空")

    options = obj.get("options") if isinstance(obj.get("options"), dict) else {}
    expected_kps = [str(kp).strip() for kp in obj.get("expected_knowledge_points") or [] if str(kp).strip()]
    if not expected_kps:
        raise CaseValidationError(f"case {case_id!r}: expected_knowledge_points 不能为空")
    min_knowledge_sections = max(1, (len(expected_kps) * 4 + 4) // 5)
    if curriculum_scope == "high_school_plus" and options.get("max_points") is not None:
        try:
            max_points = int(options["max_points"])
        except (TypeError, ValueError) as exc:
            raise CaseValidationError(f"case {case_id!r}: options.max_points 必须是整数") from exc
        if max_points < min_knowledge_sections:
            raise CaseValidationError(
                f"case {case_id!r}: high_school_plus 的 max_points={max_points} 无法覆盖 "
                f"G0 所需至少 {min_knowledge_sections} 个知识点小节"
            )
    expected_domains = [
        str(domain).strip().lower()
        for domain in obj.get("expected_domains") or []
        if str(domain).strip()
    ]
    if not expected_domains:
        raise CaseValidationError(f"case {case_id!r}: expected_domains 不能为空")

    custom_requirements = str(obj.get("requirements") or "").strip()
    combined_requirements = benchmark_output_contract(
        learning,
        curriculum_scope=curriculum_scope,
        extension_topics=extension_topics,
        min_knowledge_sections=min_knowledge_sections,
    )
    if custom_requirements:
        combined_requirements += f"；主题附加要求：{custom_requirements}"
    if len(combined_requirements) > 600:
        raise CaseValidationError(
            f"case {case_id!r}: benchmark 输出契约与 requirements 合并后超过 API 的 600 字符上限"
        )

    return BenchmarkCase(
        id=case_id,
        title=_require_str(obj, "title", case_id=case_id),
        query=_require_str(obj, "query", case_id=case_id),
        tier=tier,
        subject=str(obj.get("subject") or "").strip(),
        preset=preset,
        requirements=custom_requirements,
        options=dict(options),
        expected_knowledge_points=expected_kps,
        min_unique_sources=max(1, int(obj.get("min_unique_sources") or 1)),
        expected_domains=expected_domains,
        required_facts=facts,
        traps=traps,
        contrasts=contrasts,
        format_requirements=fmt,
        learning_requirements=learning,
        curriculum_scope=curriculum_scope,
        extension_topics=extension_topics,
    )


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并 case pack 默认值；数组和标量由具体用例整体替换。"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_case_file(path: Any) -> List[BenchmarkCase]:
    """加载单用例 JSON，或带 ``defaults`` 的多用例 case pack。"""
    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseValidationError(f"无法读取用例 {p}: {exc}") from exc
    if not isinstance(obj, dict) or "cases" not in obj:
        return [parse_case(obj, source=str(p))]

    version = obj.get("pack_version")
    if version != CASE_PACK_VERSION:
        raise CaseValidationError(
            f"用例包 {p}: pack_version 必须为 {CASE_PACK_VERSION}，实际为 {version!r}"
        )
    defaults = obj.get("defaults") or {}
    raw_cases = obj.get("cases") or []
    if not isinstance(defaults, dict):
        raise CaseValidationError(f"用例包 {p}: defaults 必须是对象")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CaseValidationError(f"用例包 {p}: cases 必须是非空数组")

    cases: List[BenchmarkCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise CaseValidationError(f"用例包 {p}: cases[{index}] 必须是对象")
        merged = _deep_merge(defaults, raw)
        cases.append(parse_case(merged, source=f"{p}#cases[{index}]"))
    return cases


def load_case(path: Any) -> BenchmarkCase:
    cases = load_case_file(path)
    if len(cases) != 1:
        raise CaseValidationError(f"{Path(path)} 包含 {len(cases)} 个用例；请使用 load_case_file")
    return cases[0]


def load_cases(cases_dir: Optional[Any] = None) -> List[BenchmarkCase]:
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
