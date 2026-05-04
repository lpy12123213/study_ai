
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List

from backend.agent.memory import SemanticDoc
from backend.agent.types import ActionResults, CompressedContext
from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_chars

logger = get_logger(__name__)

_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*?$", flags=re.M)


def _strip_markdown_headings(text: str) -> str:
    """Remove headings to keep summaries compact and avoid repeating titles."""

    raw = str(text or "")
    if not raw.strip():
        return ""
    out = _MD_HEADING_RE.sub("", raw)
    out = "\n".join([ln.rstrip() for ln in out.splitlines() if ln.strip()])
    return out.strip()


def _find_kp_entry(blob: Any, *, kp: str) -> Dict[str, Any]:
    """Best-effort lookup for payloads that follow `{items|sections:[{knowledge_point:...}, ...]}`."""

    if not kp:
        return {}
    if not isinstance(blob, dict):
        return {}
    for key in ("items", "sections"):
        entries = blob.get(key)
        if not isinstance(entries, list):
            continue
        for it in entries:
            if not isinstance(it, dict):
                continue
            if str(it.get("knowledge_point") or "").strip() == kp:
                return it
    # Also support single-entry style.
    if str(blob.get("knowledge_point") or "").strip() == kp:
        return blob
    return {}


def _extract_kp_source_text(ctx: CompressedContext, *, kp: str) -> str:
    """Gather a compact, tool-agnostic excerpt for summarization."""

    parts: List[str] = []

    try:
        gen = ctx.working_memory.get("generate_study_material")
        entry = _find_kp_entry(gen, kp=kp)
        md = str(entry.get("explanation_markdown") or "").strip()
        if md:
            parts.append(_clip_chars(_strip_markdown_headings(md), max_chars=1400))
    except Exception:
        # Best-effort only, but record failures for debugging (working_memory corruption is actionable).
        logger.warning(
            "agent_kp_source_text_extract_failed",
            extra={"kp": kp, "source": "generate_study_material"},
            exc_info=True,
        )

    try:
        synth = ctx.working_memory.get("synthesize_sources")
        entry = _find_kp_entry(synth, kp=kp)
        summary = str(entry.get("summary") or "").strip()
        if summary:
            parts.append(_clip_chars(summary, max_chars=900))
    except Exception:
        logger.warning(
            "agent_kp_source_text_extract_failed",
            extra={"kp": kp, "source": "synthesize_sources"},
            exc_info=True,
        )

    try:
        briefs = ctx.working_memory.get("source_briefs")
        brief = briefs.get(kp) if isinstance(briefs, dict) else {}
        if isinstance(brief, dict) and brief:
            # Keep it compact: definition/core_ideas is usually enough for a useful summary.
            compact = {
                "definition": brief.get("definition") if isinstance(brief.get("definition"), list) else [],
                "core_ideas": brief.get("core_ideas") if isinstance(brief.get("core_ideas"), list) else [],
                "key_properties": brief.get("key_properties") if isinstance(brief.get("key_properties"), list) else [],
            }
            parts.append(_clip_chars(json.dumps(compact, ensure_ascii=False), max_chars=900))
    except Exception:
        logger.warning(
            "agent_kp_source_text_extract_failed",
            extra={"kp": kp, "source": "source_briefs"},
            exc_info=True,
        )

    joined = "\n\n".join([p for p in parts if p.strip()]).strip()
    return _clip_chars(joined, max_chars=2200)

def build_semantic_docs_for_run(*, ctx: CompressedContext, user_input: str, markdown: str) -> List[SemanticDoc]:
    subject = str(ctx.user_profile.preferences.get("subject") or "").strip()
    topic = str(user_input or "").strip()
    now_s = time.time()

    docs: List[SemanticDoc] = []
    md_summary = _clip_chars(_strip_markdown_headings(markdown), max_chars=1600)
    if md_summary:
        docs.append(
            SemanticDoc(
                doc_id=f"run-{uuid.uuid4().hex}",
                text=md_summary,
                metadata={"subject": subject, "topic": topic, "kind": "run", "created_at_s": now_s},
            )
        )

    material_blob = ctx.working_memory.get("generate_study_material")
    material_blob = dict(material_blob) if isinstance(material_blob, dict) else {}
    sections_blob = material_blob.get("sections") if isinstance(material_blob.get("sections"), list) else []
    sections_list = [s for s in sections_blob if isinstance(s, dict)]
    for sec in sections_list[:15]:
        kp = str(sec.get("knowledge_point") or "").strip()
        md = str(sec.get("explanation_markdown") or "").strip()
        if not kp or not md:
            continue
        text = _clip_chars(_strip_markdown_headings(md), max_chars=1200)
        if not text:
            continue
        docs.append(
            SemanticDoc(
                doc_id=f"kp-{kp}-{uuid.uuid4().hex[:10]}",
                text=text,
                metadata={
                    "subject": subject,
                    "topic": topic,
                    "knowledge_point": kp,
                    "kind": "knowledge_point",
                    "created_at_s": now_s,
                },
            )
        )

    return docs


def resolve_markdown_and_archive_path(*, ctx: CompressedContext, user_input: str, results: ActionResults) -> Dict[str, str]:
    markdown = results.artifacts.get("markdown") or ctx.working_memory.get("markdown") or ""
    if not isinstance(markdown, str):
        markdown = ""

    archive_path = str(ctx.working_memory.get("archive_path") or "").strip()
    if not archive_path:
        saved = ctx.working_memory.get("save_markdown_file")
        if isinstance(saved, dict):
            archive_path = str(saved.get("path") or "").strip()

    if not markdown:
        markdown = f"# 自学材料：{user_input}\n\n（生成结果为空，建议重试或提供更具体的描述）\n"

    return {"markdown": markdown, "archive_path": archive_path}


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
