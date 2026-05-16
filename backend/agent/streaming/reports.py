from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.helpers import get_logger

logger = get_logger(__name__)

def build_per_kp_report(*, ctx: CompressedContext) -> List[Dict[str, Any]]:
    try:
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        with_diagrams_opt = study_opts.get("with_diagrams")
        with_diagrams = bool(with_diagrams_opt) if isinstance(with_diagrams_opt, bool) else True

        material_blob = ctx.working_memory.get("generate_study_material")
        if not isinstance(material_blob, dict):
            material_blob = (
                ctx.working_memory.get("study_material") if isinstance(ctx.working_memory.get("study_material"), dict) else {}
            )
        sections_blob = material_blob.get("sections") if isinstance(material_blob, dict) else None
        sections_list = [s for s in (sections_blob or []) if isinstance(s, dict)] if isinstance(sections_blob, list) else []

        preferred: List[str] = []
        split_res = ctx.working_memory.get("split_knowledge_points")
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            preferred = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()][:20]
        if not preferred:
            preferred = [
                str(s.get("knowledge_point") or "").strip()
                for s in sections_list
                if str(s.get("knowledge_point") or "").strip()
            ][:20]

        sec_by_kp: Dict[str, Dict[str, Any]] = {}
        for sec in sections_list:
            kp = str(sec.get("knowledge_point") or "").strip()
            if kp and kp not in sec_by_kp:
                sec_by_kp[kp] = sec

        def _count_list(v: Any) -> int:
            return len(v) if isinstance(v, list) else 0

        per_kp_report: List[Dict[str, Any]] = []
        for kp in preferred:
            sec = sec_by_kp.get(kp) or {}
            web_results = sec.get("web_results")
            web_pages = sec.get("web_pages")
            gh = sec.get("github") if isinstance(sec.get("github"), dict) else {}
            se = sec.get("stackexchange") if isinstance(sec.get("stackexchange"), dict) else {}

            usage = sec.get("explanation_usage") if isinstance(sec.get("explanation_usage"), dict) else {}
            try:
                total_tokens = int(usage.get("total_tokens") or 0)
            except (TypeError, ValueError):
                total_tokens = 0
            try:
                conts = int(sec.get("explanation_continuations") or 0)
            except (TypeError, ValueError):
                conts = 0
            finish_reason = str(sec.get("explanation_finish_reason") or "").strip().lower()

            diagram = sec.get("diagram") if isinstance(sec.get("diagram"), dict) else {}
            has_diagram = bool(str(diagram.get("url") or diagram.get("markdown") or "").strip())

            missing: List[str] = []
            if _count_list(web_results) < 2:
                missing.append("web_results_low")
            if _count_list(web_pages) == 0:
                missing.append("web_pages_missing")
            if finish_reason == "length" or conts > 0:
                missing.append("llm_truncated")
            if with_diagrams and not has_diagram:
                missing.append("diagram_missing")

            per_kp_report.append(
                {
                    "knowledge_point": kp,
                    "web_results": _count_list(web_results),
                    "web_pages": _count_list(web_pages),
                    "github_results": _count_list(gh.get("results")),
                    "stackexchange_results": _count_list(se.get("results")),
                    "tokens_total": total_tokens,
                    "continuations": conts,
                    "missing": missing,
                }
            )
        return per_kp_report
    except Exception:
        logger.warning("agent_per_kp_report_build_failed", exc_info=True)
        return []


def build_timing_report(*, ctx: CompressedContext, per_kp_report: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        timings_blob = ctx.working_memory.get("_tool_timings")
        timings_list = [dict(x) for x in (timings_blob or []) if isinstance(x, dict)] if isinstance(timings_blob, list) else []

        def _safe_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        ms_values: List[int] = []
        for x in timings_list:
            ms = _safe_int(x.get("elapsed_ms"))
            if ms > 0:
                ms_values.append(ms)
        ms_values.sort()

        def _pct(sorted_values: List[int], p: float) -> int:
            if not sorted_values:
                return 0
            idx = int((len(sorted_values) - 1) * p)
            idx = max(0, min(idx, len(sorted_values) - 1))
            return sorted_values[idx]

        by_tool: Dict[str, List[int]] = {}
        for it in timings_list:
            name = str(it.get("name") or "").strip() or "unknown"
            ms = _safe_int(it.get("elapsed_ms"))
            if ms <= 0:
                continue
            by_tool.setdefault(name, []).append(ms)

        by_tool_rows: List[Dict[str, Any]] = []
        for name, ms_list in by_tool.items():
            ms_list = sorted([m for m in ms_list if isinstance(m, int) and m > 0])
            if not ms_list:
                continue
            by_tool_rows.append(
                {
                    "name": name,
                    "count": len(ms_list),
                    "total_ms": sum(ms_list),
                    "p50_ms": _pct(ms_list, 0.50),
                    "p95_ms": _pct(ms_list, 0.95),
                }
            )
        by_tool_rows.sort(key=lambda x: int(x.get("total_ms") or 0), reverse=True)

        kp_count = 0
        kp_count = len(
            {
                str(x.get("knowledge_point") or "").strip()
                for x in per_kp_report
                if isinstance(x, dict) and str(x.get("knowledge_point") or "").strip()
            }
        )
        if kp_count <= 0:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                kp_count = len([str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()])

        tokens_total = 0
        for it in per_kp_report:
            if not isinstance(it, dict):
                continue
            tokens_total += _safe_int(it.get("tokens_total"))

        total_ms = sum(ms_values)
        max_tool_rows = 8
        omitted_tool_rows = max(0, len(by_tool_rows) - max_tool_rows)

        return {
            "tool_calls": len(ms_values),
            "total_elapsed_ms": total_ms,
            "p50_ms": _pct(ms_values, 0.50),
            "p95_ms": _pct(ms_values, 0.95),
            "kp_count": int(kp_count or 0),
            "avg_ms_per_kp": int(total_ms / max(1, int(kp_count or 0))),
            "tokens_total": tokens_total,
            "by_tool": by_tool_rows[:max_tool_rows],
            "by_tool_omitted": omitted_tool_rows,
        }
    except Exception:
        logger.warning("agent_timing_report_build_failed", exc_info=True)
        return {}
