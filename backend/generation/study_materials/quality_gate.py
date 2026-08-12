from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

from backend.core.text_lint import lint_text
from backend.generation.study_materials.coverage import split_sections_by_kp, unmatched_kp_titles
from backend.generation.study_materials.learning_contract import (
    LearningContractRequirements,
    inspect_learning_contract,
)
from backend.generation.study_materials.scope_contract import inspect_extension_contract

if TYPE_CHECKING:
    from backend.generation.study_materials.author.blueprint import Blueprint
    from backend.generation.study_materials.author.todos import TodoList

WORKFLOW_VERSION = 1
QUALITY_POLICY_VERSION = 3
REVIEW_SCHEMA_VERSION = 1

_ACCEPTANCE_OPTION_DEFAULTS: Dict[str, Any] = {
    "with_questions": False,
    "with_diagrams": True,
    "enable_extra_tools": False,
    "max_points": 0,
}

PRESET_PROFILES: Dict[str, Dict[str, int]] = {
    "quick": {
        "min_sources": 1,
        "min_source_classes": 1,
        "min_dimensions": 3,
        "max_review_cycles": 1,
        "max_research_cycles": 1,
        "max_consecutive_tool_failures": 3,
    },
    "standard": {
        "min_sources": 2,
        "min_source_classes": 2,
        "min_dimensions": 5,
        "max_review_cycles": 2,
        "max_research_cycles": 2,
        "max_consecutive_tool_failures": 3,
    },
    "deep": {
        "min_sources": 3,
        "min_source_classes": 2,
        "min_dimensions": 6,
        "max_review_cycles": 3,
        "max_research_cycles": 2,
        "max_consecutive_tool_failures": 3,
    },
    "research": {
        "min_sources": 4,
        "min_source_classes": 3,
        "min_dimensions": 8,
        "max_review_cycles": 4,
        "max_research_cycles": 3,
        "max_consecutive_tool_failures": 3,
    },
}


def normalize_preset(value: Any) -> str:
    preset = str(value or "standard").strip().lower() or "standard"
    return preset if preset in PRESET_PROFILES else "standard"


def draft_hash(markdown: str) -> str:
    return hashlib.sha256(str(markdown or "").encode("utf-8")).hexdigest()


def acceptance_options_fingerprint(options: Any) -> str:
    values = options if isinstance(options, dict) else {}
    try:
        max_points = int(values.get("max_points") or 0)
    except (TypeError, ValueError):
        max_points = 0
    normalized = {
        "with_questions": bool(values.get("with_questions") or values.get("enable_questions")),
        "with_diagrams": (
            bool(values.get("with_diagrams"))
            if isinstance(values.get("with_diagrams"), bool)
            else _ACCEPTANCE_OPTION_DEFAULTS["with_diagrams"]
        ),
        "enable_extra_tools": bool(values.get("enable_extra_tools")),
        "max_points": max(0, min(max_points, 15)),
    }
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def normalize_evidence(values: Any) -> List[Dict[str, Any]]:
    items = values if isinstance(values, list) else []
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        source_class = str(raw.get("source_class") or raw.get("tool") or "").strip().lower()
        title = str(raw.get("title") or "").strip()
        snippet = str(raw.get("snippet") or raw.get("summary") or raw.get("content") or "").strip()
        url = _canonical_url(raw.get("url"))
        if not source_class or not snippet:
            continue
        identity = url or hashlib.sha256(f"{source_class}|{title}|{snippet}".encode("utf-8")).hexdigest()
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(
            {
                **raw,
                "source_class": source_class,
                "title": title,
                "snippet": snippet,
                "url": url,
                "identity": identity,
            }
        )
    return normalized


def _review_dimension_names(dimensions: Any) -> set[str]:
    if not isinstance(dimensions, dict):
        return set()
    present: set[str] = set()
    for name, value in dimensions.items():
        if isinstance(value, dict) and isinstance(value.get("present"), list):
            present.update(str(item or "").strip() for item in value.get("present") or [] if str(item or "").strip())
            continue
        if isinstance(value, dict):
            covered = value.get("covered")
            if covered is None:
                covered = not bool(value.get("missing"))
            if covered:
                present.add(str(name or "").strip())
            continue
        if bool(value):
            present.add(str(name or "").strip())
    return {item for item in present if item}


def _knowledge_points(state: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    points = plan.get("knowledge_points") if isinstance(plan.get("knowledge_points"), list) else []
    return [dict(item) for item in points if isinstance(item, dict)]


def _gate_preset(state: Dict[str, Any], preset_override: Any = None) -> str:
    """Resolve the preset a gate evaluation runs under.

    B8: ``preset_override``（ deepen_research 续作传入的原始 preset）让既有内容的
    验收沿用原质量标准；缺省时回退 workflow 状态里的 preset。
    """

    override = str(preset_override or "").strip().lower()
    if override:
        return normalize_preset(override)
    return normalize_preset(state.get("preset"))


def evaluate_research(*, state: Dict[str, Any], preset_override: Any = None) -> Dict[str, Any]:
    preset = _gate_preset(state, preset_override)
    profile = PRESET_PROFILES[preset]
    research = state.get("research") if isinstance(state.get("research"), dict) else {}
    failed_checks: List[str] = []
    per_knowledge_point: Dict[str, Any] = {}
    points = list(_knowledge_points(state))
    if not points:
        failed_checks.append("plan_missing")
    for index, point in enumerate(points):
        point_id = str(point.get("id") or f"kp-{index + 1}").strip()
        evidence = normalize_evidence(research.get(point_id))
        source_classes = {str(item.get("source_class") or "") for item in evidence}
        point_failures: List[str] = []
        if len(evidence) < profile["min_sources"]:
            point_failures.append(f"research_evidence_missing:{point_id}")
        if len(source_classes) < profile["min_source_classes"]:
            point_failures.append(f"source_classes_missing:{point_id}")
        failed_checks.extend(point_failures)
        per_knowledge_point[point_id] = {
            "passed": not point_failures,
            "failed_checks": point_failures,
            "source_count": len(evidence),
            "source_classes": sorted(source_classes),
        }
    failed_checks = list(dict.fromkeys(failed_checks))
    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "per_knowledge_point": per_knowledge_point,
        "preset": preset,
        "quality_policy_version": QUALITY_POLICY_VERSION,
    }


def _kp_present_dimensions(entry: Any) -> set[str]:
    """Extract the present dimension names from one per-kp review dimensions entry."""

    if not isinstance(entry, dict):
        return set()
    present = entry.get("present")
    if isinstance(present, list):
        return {str(item or "").strip() for item in present if str(item or "").strip()}
    # 兼容按维度名嵌套的旧形状：{维度名: {"covered": bool} | bool}
    return _review_dimension_names(entry) - {"present", "missing", "facts_total"}


def evaluate_acceptance(*, state: Dict[str, Any], preset_override: Any = None) -> Dict[str, Any]:
    preset = _gate_preset(state, preset_override)
    profile = PRESET_PROFILES[preset]
    markdown = str(state.get("markdown") or "")
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    coverage_map = state.get("coverage_map") if isinstance(state.get("coverage_map"), dict) else {}

    failed_checks: List[str] = []
    per_knowledge_point: Dict[str, Any] = {}
    # 验收内嵌的检索复核同样按验收 preset 计（检索广度已由 RESEARCH 阶段门单独把关）。
    research_report = evaluate_research(state=state, preset_override=preset_override)
    failed_checks.extend(research_report["failed_checks"])
    points = list(_knowledge_points(state))
    kp_titles = [str(point.get("title") or point.get("knowledge_point") or "").strip() for point in points]
    sections_by_kp = split_sections_by_kp(markdown, kp_titles) if points else {}
    review_dimensions = review.get("dimensions") if isinstance(review.get("dimensions"), dict) else {}
    # 每个知识点必须含 定义/概念，且在此之外另具备 >= min_dimensions-2 个自身维度。
    min_kp_extra_dimensions = max(1, int(profile["min_dimensions"]) - 2)
    for index, point in enumerate(points):
        point_id = str(point.get("id") or f"kp-{index + 1}").strip()
        title = kp_titles[index] if index < len(kp_titles) else ""
        point_failures = list(
            research_report.get("per_knowledge_point", {}).get(point_id, {}).get("failed_checks", [])
        )
        section = str(sections_by_kp.get(title) or "")
        if not title or not section.strip():
            point_failures.append(f"draft_section_unmatched:{point_id}")
            failed_checks.append(f"draft_section_unmatched:{point_id}")
        # coverage_map 必须逐知识点为真，且与小节拆分交叉一致（防止全 True 的伪造 map 直接通过）。
        if not coverage_map.get(point_id) or not section.strip():
            point_failures.append(f"coverage_map_mismatch:{point_id}")
            failed_checks.append(f"coverage_map_mismatch:{point_id}")
        dims_entry = review_dimensions.get(title)
        if not isinstance(dims_entry, dict):
            dims_entry = review_dimensions.get(point_id)
        present_dims = _kp_present_dimensions(dims_entry)
        if "定义/概念" not in present_dims or len(present_dims - {"定义/概念"}) < min_kp_extra_dimensions:
            point_failures.append(f"kp_dimensions_missing:{point_id}")
            failed_checks.append(f"kp_dimensions_missing:{point_id}")
        research_point = research_report.get("per_knowledge_point", {}).get(point_id, {})
        per_knowledge_point[point_id] = {
            "passed": not point_failures,
            "failed_checks": point_failures,
            "source_count": int(research_point.get("source_count") or 0),
            "source_classes": list(research_point.get("source_classes") or []),
        }

    current_hash = draft_hash(markdown)
    if not markdown.strip():
        failed_checks.append("markdown_missing")
    lint_flags = lint_text(markdown) if markdown.strip() else []
    if lint_flags:
        failed_checks.append("markdown_lint_failed")
    if not bool(review.get("passed")):
        failed_checks.append("independent_review_failed")
    if str(review.get("draft_hash") or "") != current_hash:
        failed_checks.append("review_draft_mismatch")
    # 维度并集只保留为兜底下限；逐项要求见上面的 kp_dimensions_missing。
    dimension_names = _review_dimension_names(review.get("dimensions"))
    if len(dimension_names) < profile["min_dimensions"]:
        failed_checks.append("review_dimensions_missing")

    failed_checks = list(dict.fromkeys(failed_checks))
    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "per_knowledge_point": per_knowledge_point,
        "draft_hash": current_hash,
        "preset": preset,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "dimension_count": len(dimension_names),
        "lint_flags": lint_flags,
    }


def _archive_age_seconds(archive: Dict[str, Any]) -> Optional[float]:
    """Best-effort age of an archive row from its updated/created timestamp.

    study_archives 行里 ``updated_at``/``created_at`` 是 ISO 字符串；也兼容
    直接存放 epoch 秒的场景。无法解析时返回 None（调用方按“不新鲜”处理）。
    """

    raw = archive.get("updated_at") or archive.get("created_at")
    if raw is None or raw == "":
        return None
    timestamp: float
    if isinstance(raw, (int, float)):
        timestamp = float(raw)
    else:
        text = str(raw).strip()
        try:
            timestamp = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamp = parsed.timestamp()
    return max(0.0, time.time() - timestamp)


def acceptance_record_is_current(
    *,
    archive: Dict[str, Any],
    preset: str,
    markdown: str,
    options: Any = None,
    max_age_s: Any = None,
) -> bool:
    record = archive.get("acceptance") if isinstance(archive.get("acceptance"), dict) else {}
    try:
        policy_version = int(record.get("quality_policy_version") or 0)
        review_version = int(record.get("review_schema_version") or 0)
    except (TypeError, ValueError):
        return False
    options_match = True
    if options is not None:
        expected_options_fingerprint = acceptance_options_fingerprint(options)
        recorded_options_fingerprint = str(record.get("options_fingerprint") or "").strip()
        options_match = (
            recorded_options_fingerprint == expected_options_fingerprint
            if recorded_options_fingerprint
            else expected_options_fingerprint == acceptance_options_fingerprint(_ACCEPTANCE_OPTION_DEFAULTS)
        )
    current = bool(record.get("accepted")) and options_match and all(
        (
            str(record.get("preset") or "") == normalize_preset(preset),
            str(record.get("draft_hash") or "") == draft_hash(markdown),
            policy_version == QUALITY_POLICY_VERSION,
            review_version == REVIEW_SCHEMA_VERSION,
        )
    )
    if not current:
        return False
    if max_age_s:
        try:
            budget = float(max_age_s)
        except (TypeError, ValueError):
            budget = 0.0
        if budget > 0:
            age = _archive_age_seconds(archive)
            if age is None or age > budget:
                return False
    return True


def build_acceptance_record(*, report: Dict[str, Any], preset: str, options: Any = None) -> Dict[str, Any]:
    return {
        "accepted": bool(report.get("passed")),
        "preset": normalize_preset(preset),
        "draft_hash": str(report.get("draft_hash") or ""),
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
        "options_fingerprint": acceptance_options_fingerprint(options),
        "failed_checks": list(report.get("failed_checks") or []),
    }


# ---------------- author 运行时专用验收门 ----------------

# 组装残留的确定性占位符：[[FILL:<id>]] / [[FIG:<n>]]。
_AUTHOR_PLACEHOLDER_RE = re.compile(r"\[\[(?:FILL|FIG):")
# 正文给符号下定义的简化句型：<symbol>（紧邻）表示/代表/是<含义>。
_AUTHOR_MEANING_VERBS = ("表示", "代表", "是")
# 含义截取到就近的句读或换行为止。
_AUTHOR_MEANING_TAIL_RE = r"([^\n，。；、：,.;:]+)"


def _meanings_compatible(claimed: str, expected: str) -> bool:
    """简化确定性比较：去空白后互为子串即视为含义一致。"""

    claimed_norm = re.sub(r"\s+", "", str(claimed or ""))
    expected_norm = re.sub(r"\s+", "", str(expected or ""))
    if not claimed_norm or not expected_norm:
        return True
    return claimed_norm in expected_norm or expected_norm in claimed_norm


def _author_terminology_conflicts(markdown: str, blueprint: "Blueprint") -> List[Dict[str, Any]]:
    """正文若在术语表之外给表内符号下了与表内含义冲突的定义，记 warning（不阻断）。"""

    issues: List[Dict[str, Any]] = []
    verbs = "|".join(_AUTHOR_MEANING_VERBS)
    for term in list(getattr(blueprint, "terminology", None) or []):
        symbol = str(term.get("symbol") or "").strip()
        meaning = str(term.get("meaning") or "").strip()
        if not symbol or not meaning:
            continue
        pattern = re.compile(re.escape(symbol) + rf"\s*(?:{verbs})\s*" + _AUTHOR_MEANING_TAIL_RE)
        for match in pattern.finditer(markdown):
            claimed = match.group(1).strip()
            if not claimed or _meanings_compatible(claimed, meaning):
                continue
            issues.append(
                {
                    "code": "terminology_conflict",
                    "severity": "warning",
                    "symbol": symbol,
                    "expected": meaning,
                    "found": claimed,
                    "detail": f"正文将 {symbol} 定义为「{claimed}」，与术语表「{meaning}」不一致",
                }
            )
            break  # 每个符号只记第一条冲突，避免刷屏
    return issues


def evaluate_author_acceptance(
    *,
    todos: "TodoList",
    markdown: str,
    blueprint: "Blueprint",
    learning_requirements: LearningContractRequirements | None = None,
    knowledge_points: List[str] | None = None,
    min_knowledge_sections: int = 0,
    extension_topics: List[str] | None = None,
) -> Dict[str, Any]:
    """author 运行时的成稿验收门（与 state 驱动的 evaluate_acceptance 并存，互不改用）。

    硬门槛（error，阻断）：todos 未清零（``todos_not_cleared``）、成稿残留
    ``[[FILL:``/``[[FIG:`` 占位符（``placeholder_residual``）、知识点拆分或小节覆盖不足，
    以及受控拓展未逐项回连高中。请求练习闭环时，整篇契约不完整
    （``learning_contract_unmet``）也作为硬门槛；
    软提示（warning，不阻断）：正文与术语表含义冲突（``terminology_conflict``）。
    返回包络沿用 evaluate_acceptance 惯例；``issues`` 为含 ``code``/``severity``
    的 dict 列表，``failed_checks`` 取其中 error 级 issue 的 code。
    """

    text = str(markdown or "")
    issues: List[Dict[str, Any]] = []

    if not todos.all_cleared():
        uncleared = [it.id for it in todos.items if it.status not in {"done", "waived"}]
        issues.append(
            {
                "code": "todos_not_cleared",
                "severity": "error",
                "todos": uncleared,
                "detail": f"存在未清零的 TODO（须为 done/waived）：{', '.join(uncleared)}",
            }
        )

    if _AUTHOR_PLACEHOLDER_RE.search(text):
        residual = sorted({m.group(0) for m in _AUTHOR_PLACEHOLDER_RE.finditer(text)})
        issues.append(
            {
                "code": "placeholder_residual",
                "severity": "error",
                "placeholders": residual,
                "detail": f"成稿残留未替换占位符：{', '.join(residual)}",
            }
        )

    points = list(dict.fromkeys(str(point).strip() for point in (knowledge_points or []) if str(point).strip()))
    minimum = max(0, int(min_knowledge_sections or 0))
    if minimum and len(points) < minimum:
        issues.append(
            {
                "code": "knowledge_point_count_unmet",
                "severity": "error",
                "actual": len(points),
                "required": minimum,
                "detail": f"知识点拆分数量不足：{len(points)}/{minimum}",
            }
        )
    if points:
        sections_by_kp = split_sections_by_kp(text, points)
        uncovered = unmatched_kp_titles(sections_by_kp)
        if uncovered:
            issues.append(
                {
                    "code": "knowledge_coverage_unmet",
                    "severity": "error",
                    "uncovered": uncovered,
                    "covered": len(points) - len(uncovered),
                    "required": len(points),
                    "detail": "成稿缺少知识点小节：" + "、".join(uncovered),
                }
            )

    extension = inspect_extension_contract(text, extension_topics or [])
    if not extension["passed"]:
        issues.append(
            {
                "code": "extension_contract_unmet",
                "severity": "error",
                "metrics": extension,
                "detail": (
                    "受控拓展未逐项回连高中：缺少主题="
                    + "、".join(extension["missing_topics"] or ["无"])
                    + "；缺少连接="
                    + "、".join(extension["missing_connections"] or ["无"])
                ),
            }
        )

    if learning_requirements is not None:
        learning = inspect_learning_contract(text, learning_requirements)
        if not learning["passed"]:
            issues.append(
                {
                    "code": "learning_contract_unmet",
                    "severity": "error",
                    "missing": list(learning["missing"]),
                    "metrics": {
                        key: learning[key]
                        for key in (
                            "objective_count",
                            "prerequisites_ok",
                            "worked_examples",
                            "question_count",
                            "paired_count",
                            "level_hits",
                            "rubric_ok",
                        )
                    },
                    "detail": "整篇学习闭环未达标：" + "；".join(learning["missing"]),
                }
            )

    issues.extend(_author_terminology_conflicts(text, blueprint))

    failed_checks = list(dict.fromkeys(issue["code"] for issue in issues if issue["severity"] == "error"))
    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "issues": issues,
        "quality_policy_version": QUALITY_POLICY_VERSION,
    }
