"""引用与学术规范评分：C 维度。

Challenge v2 不再按“有两条 URL 就满分”计分：参考文献数量必须达到用例门槛，
内联标记必须与带 URL 的文末定义真实对应，且参考文献需覆盖用例指定的权威域名。
联网可访问性抽查保留为诊断信息，不改变离线可复现的百分制结果。
"""

from __future__ import annotations

import re
from math import ceil
from typing import Callable, Optional, Tuple
from urllib.parse import urlsplit

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

_REFS_HEADING_RE = re.compile(r"^#{1,4}\s*(参考文献|参考资料|引用文献|引用来源|来源|References|Bibliography|Sources)\s*$", re.IGNORECASE | re.M)
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)）】]+")
_FOOTNOTE_MARK_RE = re.compile(r"\[\^([^\]]+)\]")
_NUMERIC_MARK_RE = re.compile(r"\[(\d{1,2})\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\s*(?:[-*+]\s*)?\[\^([^\]]+)\]:?\s*(.*)$", re.M)
_NUMERIC_DEF_RE = re.compile(r"^\s*(?:[-*+]\s*)?\[(\d{1,2})\][.:：]?\s*(.*)$", re.M)

# (url) -> 是否可访问；由 runner 注入（--check-links），离线时为 None。
LinkChecker = Callable[[str], bool]


def _split_references(markdown: str) -> Tuple[str, str]:
    """(正文, 参考文献小节正文)；无参考文献小节时后者为 ""。"""
    m = _REFS_HEADING_RE.search(markdown or "")
    if not m:
        return markdown or "", ""
    body = markdown[: m.start()]
    refs = markdown[m.end():]
    # 小节到下一个同级或更高级标题为止
    next_heading = re.search(r"^#{1,4}\s", refs, re.M)
    if next_heading:
        refs = refs[: next_heading.start()]
    return body, refs


def _urls(text: str) -> list[str]:
    return [url.rstrip(".,;:!?，。；：！？") for url in _URL_RE.findall(text or "")]


def _citation_sets(markdown: str) -> tuple[set[str], set[str]]:
    """返回（正文标记，带 URL 的文末定义），并区分脚注/数字命名空间。"""
    body, refs = _split_references(markdown)
    marks = {f"f:{value}" for value in _FOOTNOTE_MARK_RE.findall(body)}
    marks.update(f"n:{value}" for value in _NUMERIC_MARK_RE.findall(body))
    definitions: set[str] = set()
    for value, rest in _FOOTNOTE_DEF_RE.findall(refs):
        if _urls(rest):
            definitions.add(f"f:{value}")
    for value, rest in _NUMERIC_DEF_RE.findall(refs):
        if _urls(rest):
            definitions.add(f"n:{value}")
    return marks, definitions


def valid_inline_citation_ids(markdown: str) -> set[str]:
    """供知识评分器使用：正文中确有带 URL 文末定义的引用标记。"""
    marks, definitions = _citation_sets(markdown)
    return marks & definitions


def grade_citations(
    case: BenchmarkCase,
    markdown: str,
    *,
    link_checker: Optional[LinkChecker] = None,
) -> DimensionResult:
    """C 维度：引用与学术规范（满分 DIMENSION_MAX['C']）。"""
    dim = make_dimension("C")
    total_max = DIMENSION_MAX["C"]
    text = markdown or ""
    _body, refs = _split_references(text)

    # C1（30%）：参考文献数量与检索要求同标尺，避免“两条 URL 即满分”。
    c1_max = total_max * 0.30
    ref_urls = list(dict.fromkeys(_urls(refs)))
    target_refs = max(1, case.min_unique_sources)
    c1_ratio = min(1.0, len(ref_urls) / target_refs) if refs else 0.0
    c1_detail = f"参考文献 URL {len(ref_urls)}/{target_refs}"
    if not refs:
        c1_detail += "；无参考文献小节（检索结果未进入成稿）"
    dim.checks.append(CheckResult(
        "C1_references_section",
        "参考文献小节与来源数量达标",
        c1_max * c1_ratio,
        c1_max,
        c1_detail,
        metrics={"reference_count": len(ref_urls), "target": target_refs},
    ))

    # C2（50%）：只有能映射到带 URL 定义的标记才算；数量随事实检查点增长。
    c2_max = total_max * 0.50
    marks, definitions = _citation_sets(text)
    valid_marks = marks & definitions
    target_inline = max(1, ceil(len(case.required_facts) * 0.8))
    coverage_ratio = min(1.0, len(valid_marks) / target_inline)
    integrity_ratio = len(valid_marks) / len(marks) if marks else 0.0
    c2_ratio = 0.80 * coverage_ratio + 0.20 * integrity_ratio
    c2_detail = (
        f"有效内联引用 {len(valid_marks)}/{target_inline}；"
        f"正文标记 {len(marks)} 个，带 URL 定义 {len(definitions)} 个"
    )
    dim.checks.append(CheckResult(
        "C2_inline_markers",
        "关键论断的内联引用与文末来源一一对应",
        c2_max * c2_ratio,
        c2_max,
        c2_detail,
        metrics={
            "valid_inline_count": len(valid_marks),
            "target": target_inline,
            "integrity_ratio": round(integrity_ratio, 4),
        },
    ))

    # C3（20%）：离线按权威域名覆盖评分；联网抽查只写入 detail，避免网络波动改分。
    c3_max = total_max * 0.20
    ref_domains: set[str] = set()
    for url in ref_urls:
        try:
            host = urlsplit(url).netloc.lower()
        except ValueError:
            continue
        if host:
            ref_domains.add(host)
    expected = case.expected_domains
    authority_hits = [
        domain
        for domain in expected
        if any(host == domain or host.endswith("." + domain) for host in ref_domains)
    ]
    target_domains = max(1, ceil(len(expected) * 2 / 3)) if expected else 3
    authority_ratio = min(1.0, len(authority_hits) / target_domains)
    c3_detail = f"权威域名 {len(authority_hits)}/{target_domains}: {authority_hits or '无'}"
    if link_checker is not None and ref_urls:
        sample = ref_urls[:5]
        reachable = sum(1 for url in sample if _safe_check(link_checker, url))
        c3_detail += f"；链接抽查 {reachable}/{len(sample)}（诊断项，不改变分数）"
    elif link_checker is None:
        c3_detail += "；未联网抽查（不影响离线分数）"
    dim.checks.append(CheckResult(
        "C3_authority_domains",
        "参考文献覆盖用例指定的权威来源",
        c3_max * authority_ratio,
        c3_max,
        c3_detail,
        metrics={"authority_hits": authority_hits, "target": target_domains},
    ))
    return dim


def _safe_check(link_checker: LinkChecker, url: str) -> bool:
    try:
        return bool(link_checker(url))
    except Exception:  # noqa: BLE001 - 网络异常按不可访问计
        return False
