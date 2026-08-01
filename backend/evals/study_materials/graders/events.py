"""事件流评分：R 多步检索过程、S 子代理使用。

输入是 SSE 帧字典列表（``{taskId, seq, type, data}``），全部确定性判定：
- R 看检索工具调用的类别数、深读行为、唯一来源数、检索轮次与权威域名命中；
- S 看 subagent_start/subagent_end 事件、知识点覆盖率与摘要产出。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlsplit

from backend.evals.study_materials.case_schema import BenchmarkCase
from backend.evals.study_materials.graders.common import (
    DIMENSION_MAX,
    PROCESS_DIMENSION_MAX,
    CheckResult,
    DimensionResult,
    make_dimension,
)

# 检索类工具 → 来源类别。browse 单列：它代表"深读网页"而非一次新检索。
SEARCH_TOOL_CLASSES: Dict[str, str] = {
    "web_search_knowledge": "web",
    "wikipedia_search": "wikipedia",
    "mediawiki_search": "mediawiki",
    "github_search": "github",
    "stackexchange_search": "stackexchange",
    "aggregate_knowledge": "aggregate",
    "synthesize_sources": "aggregate",
    "deep_research": "web",
}
DEEP_READ_TOOLS = {"browse_web_pages"}

_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)）】，,；;]+")


class EventStats:
    """从事件帧中抽取的检索/子代理统计量。"""

    def __init__(self, events: List[Dict[str, Any]], task_info: Optional[Dict[str, Any]] = None) -> None:
        self.tool_calls: List[Dict[str, Any]] = []
        self.tool_results: List[Dict[str, Any]] = []
        self.subagent_starts: List[Dict[str, Any]] = []
        self.subagent_ends: List[Dict[str, Any]] = []
        self.done: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None
        # SSE 会裁剪大 tool_result（输出变成 "[N items]" 占位串），
        # task_info.search_summary_by_kp 保留完整检索结果，作为来源统计的补充输入。
        self.task_info = task_info if isinstance(task_info, dict) else {}
        for frame in events:
            if not isinstance(frame, dict):
                continue
            ftype = str(frame.get("type") or frame.get("event") or "")
            data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
            if ftype == "tool_call":
                self.tool_calls.append(data)
            elif ftype == "tool_result":
                self.tool_results.append(data)
            elif ftype == "subagent_start":
                self.subagent_starts.append(data)
            elif ftype == "subagent_end":
                self.subagent_ends.append(data)
            elif ftype == "done":
                self.done = data
            elif ftype == "error":
                self.error = data

    # ---- 检索统计 ----

    def search_calls(self) -> List[Dict[str, Any]]:
        return [c for c in self.tool_calls if str(c.get("name") or "") in SEARCH_TOOL_CLASSES]

    def source_classes(self) -> Set[str]:
        return {SEARCH_TOOL_CLASSES[str(c.get("name"))] for c in self.search_calls()}

    def deep_read_count(self) -> int:
        return sum(1 for c in self.tool_calls if str(c.get("name") or "") in DEEP_READ_TOOLS)

    def distinct_search_payloads(self) -> int:
        """检索轮次近似：不同检索入参（query 改写/重试）的数量。"""
        payloads: Set[str] = set()
        for call in self.search_calls():
            args = call.get("arguments")
            payloads.add(json.dumps(args if args is not None else {}, ensure_ascii=False, sort_keys=True))
        return len(payloads)

    def _task_info_urls(self) -> Set[str]:
        """从 task_info.search_summary_by_kp[*].results[*].url 抽取完整来源 URL。"""
        urls: Set[str] = set()
        summaries = self.task_info.get("search_summary_by_kp")
        if not isinstance(summaries, dict):
            return urls
        for value in summaries.values():
            if not isinstance(value, dict):
                continue
            results = value.get("results")
            if not isinstance(results, list):
                continue
            for item in results:
                if isinstance(item, dict):
                    url = str(item.get("url") or "").strip()
                    if url.startswith("http"):
                        urls.add(url)
        return urls

    def result_urls(self) -> Set[str]:
        """tool_result 输出 + task_info 检索摘要里出现过的全部 URL。"""
        urls: Set[str] = set(self._task_info_urls())
        for result in self.tool_results:
            blob = json.dumps(result, ensure_ascii=False, default=str)
            for match in _URL_RE.findall(blob):
                urls.add(match.rstrip(".,;:)\"]}"))
        return urls

    def result_domains(self) -> Set[str]:
        domains: Set[str] = set()
        for url in self.result_urls():
            try:
                host = urlsplit(url).netloc.lower()
            except ValueError:
                continue
            if host:
                domains.add(host)
        return domains

    # ---- 子代理统计 ----

    def subagent_knowledge_points(self) -> Set[str]:
        points: Set[str] = set()
        for data in self.subagent_starts:
            kp = str(data.get("knowledge_point") or data.get("kp") or "").strip()
            if kp:
                points.add(kp)
        return points

    def subagent_summaries_count(self) -> int:
        count = 0
        for data in self.subagent_ends:
            summary = data.get("summary")
            if isinstance(summary, str) and summary.strip():
                count += 1
        return count


def grade_research(
    case: BenchmarkCase,
    events: List[Dict[str, Any]],
    task_info: Optional[Dict[str, Any]] = None,
) -> DimensionResult:
    """R 维度：多步检索过程（满分 DIMENSION_MAX['R']）。"""
    stats = EventStats(events, task_info=task_info)
    kp_count = max(1, len(case.expected_knowledge_points))
    dim = make_dimension("R")
    total_max = DIMENSION_MAX["R"]
    part = total_max / 5.0

    classes = stats.source_classes()
    n_classes = len(classes)
    score = part if n_classes >= 3 else (part * 0.6 if n_classes == 2 else (part * 0.25 if n_classes == 1 else 0.0))
    dim.checks.append(CheckResult(
        "R1_source_classes", "检索来源类别数 ≥3（web/wikipedia/mediawiki/github/…）",
        score, part, f"命中 {n_classes} 类: {sorted(classes) or '无'}",
    ))

    deep_reads = stats.deep_read_count()
    ratio = deep_reads / kp_count
    score = part if ratio >= 1.0 else (part * 0.5 if ratio >= 0.5 else (part * 0.25 if deep_reads > 0 else 0.0))
    dim.checks.append(CheckResult(
        "R2_deep_reads", "每个知识点至少一次深读（browse_web_pages）",
        score, part, f"深读 {deep_reads} 次 / {kp_count} 个知识点",
    ))

    urls = stats.result_urls()
    score = part * min(1.0, len(urls) / max(1, case.min_unique_sources))
    detail = f"实际 {len(urls)} 个"
    if stats.task_info:
        detail += "（含 task_info 检索摘要补全，SSE 对大输出有裁剪）"
    dim.checks.append(CheckResult(
        "R3_unique_sources", f"唯一来源 URL 数 ≥ {case.min_unique_sources}",
        score, part, detail,
    ))

    rounds = stats.distinct_search_payloads()
    score = part if rounds >= 2 * kp_count else (part * 0.5 if rounds >= kp_count else (part * 0.25 if rounds > 0 else 0.0))
    dim.checks.append(CheckResult(
        "R4_multi_round", "多轮检索（query 改写/重试/多供应商）≥ 2×知识点数",
        score, part, f"不同检索入参 {rounds} 个 / 阈值 {2 * kp_count}",
    ))

    domains = stats.result_domains()
    expected = case.expected_domains
    if expected:
        hits = [d for d in expected if any(host == d or host.endswith("." + d) for host in domains)]
        score = part * (len(hits) / len(expected))
        detail = f"权威域名命中 {len(hits)}/{len(expected)}: {hits or '无'}"
    else:
        score, detail = 0.0, "用例未配置 expected_domains"
    dim.checks.append(CheckResult(
        "R5_authority_domains", "权威来源域名命中（用例 expected_domains）",
        score, part, detail,
    ))
    return dim


def grade_subagents(case: BenchmarkCase, events: List[Dict[str, Any]]) -> DimensionResult:
    """S 过程诊断：子代理使用（不计入最终百分制）。

    默认 ReAct 路径不产生 subagent 事件（仅 plan 模式 foreach 块触发），
    这是"真实需要"缺口之一：本维度对当前系统天然接近 0 分。
    """
    stats = EventStats(events)
    kp_count = max(1, len(case.expected_knowledge_points))
    dim = make_dimension("S")
    total_max = PROCESS_DIMENSION_MAX["S"]
    part = total_max / 3.0

    n_start = len(stats.subagent_starts)
    dim.checks.append(CheckResult(
        "S1_spawned", "出现 per-kp 子代理（subagent_start 事件）",
        part if n_start > 0 else 0.0, part,
        f"subagent_start {n_start} 个" if n_start else "无任何 subagent 事件（默认 ReAct 路径不派发子代理）",
    ))

    covered = stats.subagent_knowledge_points()
    ratio = len(covered) / kp_count
    score = part if ratio >= 0.8 else (part * 0.5 if ratio >= 0.5 else (part * 0.25 if covered else 0.0))
    dim.checks.append(CheckResult(
        "S2_kp_coverage", "子代理知识点覆盖率 ≥ 80%",
        score, part, f"覆盖 {len(covered)}/{kp_count} 个知识点",
    ))

    n_end = len(stats.subagent_ends)
    n_summary = stats.subagent_summaries_count()
    score = part * (n_summary / n_end) if n_end else 0.0
    dim.checks.append(CheckResult(
        "S3_summaries", "子代理结束产生摘要（成果回注主上下文）",
        score, part, f"含摘要 {n_summary}/{n_end} 个子代理",
    ))
    return dim
