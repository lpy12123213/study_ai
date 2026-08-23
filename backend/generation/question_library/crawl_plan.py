"""爬取关键词计划构造（CLI 批量导入与任务 runner 共用）。

原先只有 CLI 支持按知识域/自定义关键词批量构造计划；抽出共享模块后，
`/api/question-library/crawl` 任务也能用同一套计划语义按域批量补题。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

DEFAULT_PHYSICS_MECHANICS_KEYWORDS = (
    "力学",
    "运动学",
    "匀变速直线运动",
    "牛顿运动定律",
    "受力分析",
    "共点力平衡",
    "圆周运动",
    "万有引力",
    "功和能",
    "动能定理",
    "机械能守恒",
    "动量守恒",
    "碰撞",
    "抛体运动",
    "运动合成与分解",
    "弹簧模型",
    "板块模型",
    "传送带",
    "绳连接体",
    "力矩",
)

DEFAULT_PHYSICS_ELECTROMAGNETISM_KEYWORDS = (
    "电磁学",
    "电场",
    "库仑定律",
    "电势能",
    "电容器",
    "带电粒子电场",
    "恒定电流",
    "欧姆定律",
    "闭合电路欧姆定律",
    "电路动态分析",
    "磁场",
    "安培力",
    "洛伦兹力",
    "带电粒子磁场",
    "电磁感应",
    "法拉第电磁感应定律",
    "楞次定律",
    "交流电",
    "变压器",
    "带电粒子复合场",
)

DOMAIN_ALIASES = {
    "all": "all",
    "physics": "all",
    "physics-core": "all",
    "mechanics": "力学",
    "mechanic": "力学",
    "力学": "力学",
    "electromagnetism": "电磁学",
    "electromag": "电磁学",
    "电磁学": "电磁学",
}


@dataclass(frozen=True)
class KeywordPlanItem:
    domain: str
    query: str


def normalize_domains(values: Iterable[str]) -> tuple[str, ...]:
    domains: list[str] = []
    for value in values:
        raw = str(value or "").strip()
        normalized = DOMAIN_ALIASES.get(raw.lower()) or DOMAIN_ALIASES.get(raw)
        if not normalized:
            raise ValueError(f"unsupported_domain: {raw}")
        if normalized == "all":
            return ("all",)
        if normalized not in domains:
            domains.append(normalized)
    return tuple(domains or ["all"])


def build_keyword_plan(*, custom_keywords: Iterable[str] = (), domains: Iterable[str] = ("all",)) -> list[KeywordPlanItem]:
    """构造爬取计划：自定义关键词优先；否则按域取默认关键词表（力学/电磁学交错）。"""

    if custom_keywords:
        resolved = normalize_domains(domains)
        domain = "力学" if resolved == ("力学",) else "电磁学" if resolved == ("电磁学",) else "自定义"
        return [KeywordPlanItem(domain=domain, query=query) for query in custom_keywords if str(query).strip()]

    resolved = normalize_domains(domains)
    include_mechanics = resolved == ("all",) or "力学" in resolved
    include_electromag = resolved == ("all",) or "电磁学" in resolved

    plan: list[KeywordPlanItem] = []
    mechanics_plan = [
        KeywordPlanItem(domain="力学", query=query)
        for query in DEFAULT_PHYSICS_MECHANICS_KEYWORDS
        if include_mechanics
    ]
    electromag_plan = [
        KeywordPlanItem(domain="电磁学", query=query)
        for query in DEFAULT_PHYSICS_ELECTROMAGNETISM_KEYWORDS
        if include_electromag
    ]
    if mechanics_plan and electromag_plan:
        for index in range(max(len(mechanics_plan), len(electromag_plan))):
            if index < len(mechanics_plan):
                plan.append(mechanics_plan[index])
            if index < len(electromag_plan):
                plan.append(electromag_plan[index])
    else:
        plan.extend(mechanics_plan)
        plan.extend(electromag_plan)
    return plan
