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
