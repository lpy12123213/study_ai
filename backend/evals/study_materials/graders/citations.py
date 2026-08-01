"""引用与学术规范评分：C 维度。

现行汇编逻辑（``study_archive.py``）收集了 ``refs_by_kp`` 但从不渲染，
成稿既无参考文献小节也无内联引用标记——本维度对当前系统天然为 0，
是 benchmark 反映"真实需要"的主要缺口之一。
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Tuple

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import DIMENSION_MAX, CheckResult, DimensionResult, make_dimension

_REFS_HEADING_RE = re.compile(r"^#{1,4}\s*(参考文献|参考资料|引用文献|引用来源|来源|References|Bibliography|Sources)\s*$", re.IGNORECASE | re.M)
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)）】]+")
_FOOTNOTE_MARK_RE = re.compile(r"\[\^([^\]]+)\]")
_NUMERIC_MARK_RE = re.compile(r"\[(\d{1,2})\]")

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


def grade_citations(
    case: BenchmarkCase,
    markdown: str,
    *,
    link_checker: Optional[LinkChecker] = None,
) -> DimensionResult:
    """C 维度：引用与学术规范（满分 DIMENSION_MAX['C']）。"""
    dim = make_dimension("C")
    total_max = DIMENSION_MAX["C"]
    part = total_max / 3.0
    text = markdown or ""
    body, refs = _split_references(text)

    # C1 参考文献小节
    ref_urls = _URL_RE.findall(refs)
    if refs and len(ref_urls) >= 2:
        c1 = part
        c1_detail = f"参考文献小节含 {len(ref_urls)} 条 URL"
    elif refs:
        c1 = part * 0.25
        c1_detail = "有参考文献小节但可溯源条目不足（<2 条 URL）"
    else:
        c1 = 0.0
        c1_detail = "无参考文献小节（现行汇编只收集不渲染引用）"
    dim.checks.append(CheckResult("C1_references_section", "参考文献小节存在且条目可溯源", c1, part, c1_detail))

    # C2 内联引用标记与文末一一对应
    footnote_marks = set(_FOOTNOTE_MARK_RE.findall(body))
    numeric_marks = set(_NUMERIC_MARK_RE.findall(body))
    footnote_defs = set(re.findall(r"^\s*(?:[-*+]\s*)?\[\^([^\]]+)\]:", refs or text, re.M))
    matched = len(footnote_marks & footnote_defs)
    if numeric_marks and ref_urls:
        matched += min(len(numeric_marks), len(ref_urls))
    total_marks = len(footnote_marks) + len(numeric_marks)
    if total_marks and matched:
        c2 = part * min(1.0, matched / 5.0) * (matched / total_marks)
        c2_detail = f"内联标记 {total_marks} 个，可对应 {matched} 个"
    else:
        c2 = 0.0
        c2_detail = "正文无内联引用标记（写手 prompt 目前明确禁止输出引用标记）"
    dim.checks.append(CheckResult("C2_inline_markers", "内联引用标记与参考文献一一对应", c2, part, c2_detail))

    # C3 来源可访问性抽查
    if link_checker is not None and ref_urls:
        sample = list(dict.fromkeys(ref_urls))[:5]
        ok = sum(1 for url in sample if _safe_check(link_checker, url))
        c3 = part * (ok / len(sample))
        c3_detail = f"抽查 {len(sample)} 条 URL，{ok} 条可访问"
    elif link_checker is None:
        c3, c3_detail = 0.0, "未启用链接抽查（runner 加 --check-links）"
    else:
        c3, c3_detail = 0.0, "无 URL 可抽查"
    dim.checks.append(CheckResult("C3_link_check", "来源链接可访问性抽查", c3, part, c3_detail))
    return dim


def _safe_check(link_checker: LinkChecker, url: str) -> bool:
    try:
        return bool(link_checker(url))
    except Exception:  # noqa: BLE001 - 网络异常按不可访问计
        return False
