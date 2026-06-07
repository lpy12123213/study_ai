from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.agent.tools.utils.text_utils import credibility_for_url
from backend.core.text_utils import clip_text as _clip_text
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry


def _source_synthesis_system_prompt() -> str:
    return create_default_prompt_registry().render("agent.tool.source_synthesis.v1").content


def _extract_points(args: Dict[str, Any], ctx: CompressedContext) -> List[str]:
    provided = args.get("knowledge_points")
    if isinstance(provided, list):
        pts = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if pts:
            return pts[:15]

    split_res = ctx.working_memory.get("split_knowledge_points")
    if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
        pts = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
        if pts:
            return pts[:15]

    topic = str(args.get("topic") or ctx.current_task or "").strip()
    return [topic] if topic else []


class SourceSynthesisToolsMixin:
    async def _tool_synthesize_sources(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Synthesize noisy multi-source retrieval into a structured, writer-friendly brief.

        Writes:
        - ctx.working_memory["source_briefs"][knowledge_point] = source_brief (dict)
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]

        points = _extract_points(args, ctx)

        aggregated = ctx.working_memory.get("aggregated") or ctx.working_memory.get("aggregate_knowledge") or {}
        agg_items = (
            aggregated.get("items")
            if isinstance(aggregated, dict) and isinstance(aggregated.get("items"), list)
            else []
        )
        agg_items = [x for x in agg_items if isinstance(x, dict)]
        agg_by_kp = {
            str(x.get("knowledge_point") or "").strip(): x
            for x in agg_items
            if str(x.get("knowledge_point") or "").strip()
        }

        max_web_results = max(3, min(int(args.get("max_web_results") or 10), 30))
        max_web_pages = max(0, min(int(args.get("max_web_pages") or 2), 8))
        max_page_chars = max(800, min(int(args.get("max_page_chars") or 2600), 12000))

        model = str(
            os.getenv("STUDY_MATERIALS_SYNTHESIS_MODEL")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        async def _synthesize_one(kp: str) -> Dict[str, Any]:
            it = agg_by_kp.get(kp) or {}
            wiki = it.get("wikipedia") if isinstance(it.get("wikipedia"), dict) else {}
            mw = it.get("mediawiki") if isinstance(it.get("mediawiki"), dict) else {}
            web = it.get("web_search") if isinstance(it.get("web_search"), dict) else {}
            pages_blob = it.get("web_pages") if isinstance(it.get("web_pages"), dict) else {}
            gh = it.get("github") if isinstance(it.get("github"), dict) else {}
            se = it.get("stackexchange") if isinstance(it.get("stackexchange"), dict) else {}

            sources: List[Dict[str, Any]] = []

            wiki_summary = _clip_text(str(wiki.get("summary") or wiki.get("content") or ""), 2200)
            if wiki_summary:
                sources.append(
                    {
                        "id": "wiki",
                        "kind": "wikipedia",
                        "title": str(wiki.get("title") or "Wikipedia"),
                        "text": wiki_summary,
                    }
                )

            mw_summary = _clip_text(str(mw.get("summary") or mw.get("content") or ""), 2200)
            if mw_summary:
                sources.append(
                    {"id": "mw", "kind": "mediawiki", "title": str(mw.get("title") or "MediaWiki"), "text": mw_summary}
                )

            web_summary = _clip_text(str(web.get("summary") or ""), 2400)
            if web_summary:
                sources.append(
                    {"id": "web_summary", "kind": "web_summary", "title": "Web summary", "text": web_summary}
                )

            web_results = web.get("results") if isinstance(web.get("results"), list) else []
            for idx, r in enumerate([x for x in web_results if isinstance(x, dict)][:max_web_results]):
                title = str(r.get("title") or "").strip()
                url = str(r.get("url") or "").strip()
                snippet = str(r.get("snippet") or r.get("text") or "").strip()
                snippet = _clip_text(snippet, 480)
                if len(snippet) < 40 and not title:
                    continue
                cred = r.get("credibility_score")
                if cred is None:
                    _, cred = credibility_for_url(url)
                quality_flags = list(r.get("quality_flags") or []) if isinstance(r.get("quality_flags"), list) else []
                sources.append(
                    {
                        "id": f"web:{idx}",
                        "kind": "web_result",
                        "title": title or url or f"web:{idx}",
                        "url": url,
                        "domain": str(r.get("domain") or "").strip(),
                        "credibility": round(float(cred or 0.45), 3),
                        "quality_flags": quality_flags,
                        "text": snippet,
                    }
                )

            pages = pages_blob.get("pages") if isinstance(pages_blob.get("pages"), list) else []
            for idx, p in enumerate([x for x in pages if isinstance(x, dict)][:max_web_pages]):
                title = str(p.get("title") or "").strip()
                url = str(p.get("url") or "").strip()
                text = str(p.get("text") or p.get("content") or p.get("excerpt") or "").strip()
                text = _clip_text(text, max_page_chars)
                if len(text) < 120:
                    continue
                cred = p.get("credibility_score")
                if cred is None:
                    _, cred = credibility_for_url(url)
                quality_flags = list(p.get("quality_flags") or []) if isinstance(p.get("quality_flags"), list) else []
                sources.append(
                    {
                        "id": f"page:{idx}",
                        "kind": "web_page",
                        "title": title or url or f"page:{idx}",
                        "url": url,
                        "domain": str(p.get("domain") or "").strip(),
                        "credibility": round(float(cred or 0.45), 3),
                        "quality_flags": quality_flags,
                        "text": text,
                    }
                )

            # Optional: a couple of high-signal entries from GH / StackExchange.
            gh_results = gh.get("results") if isinstance(gh.get("results"), list) else []
            for idx, r in enumerate([x for x in gh_results if isinstance(x, dict)][:3]):
                title = str(r.get("full_name") or r.get("name") or r.get("title") or "").strip()
                text = _clip_text(str(r.get("description") or r.get("snippet") or ""), 320)
                if not title and not text:
                    continue
                sources.append({"id": f"gh:{idx}", "kind": "github", "title": title or f"github:{idx}", "text": text})

            se_results = se.get("results") if isinstance(se.get("results"), list) else []
            for idx, r in enumerate([x for x in se_results if isinstance(x, dict)][:3]):
                title = str(r.get("title") or "").strip()
                text = _clip_text(str(r.get("excerpt") or r.get("snippet") or ""), 420)
                if not title and not text:
                    continue
                sources.append(
                    {
                        "id": f"se:{idx}",
                        "kind": "stackexchange",
                        "title": title or f"stackexchange:{idx}",
                        "url": str(r.get("url") or "").strip(),
                        "text": text,
                    }
                )

            # Keep the payload compact. Rank web-class sources by credibility before truncation
            # so the LLM sees the most trustworthy sources first (other kinds stay at the front).
            sources = [s for s in sources if isinstance(s, dict) and str(s.get("text") or "").strip()]
            _web_kinds = {"web_result", "web_page", "web_summary"}
            _non_web = [s for s in sources if s.get("kind") not in _web_kinds]
            _web = [s for s in sources if s.get("kind") in _web_kinds]
            _credibility_min = float(os.getenv("STUDY_MATERIALS_CREDIBILITY_FILTER_MIN") or 0.0)
            if _credibility_min > 0:
                _filtered = [s for s in _web if float(s.get("credibility") or 0.45) >= _credibility_min]
                # Don't starve the writer: keep top-3 by credibility if filter removed everything.
                if not _filtered and _web:
                    _filtered = sorted(_web, key=lambda x: float(x.get("credibility") or 0.0), reverse=True)[:3]
                _web = _filtered
            _web.sort(key=lambda x: float(x.get("credibility") or 0.0), reverse=True)
            sources = (_non_web + _web)[:18]

            if not is_llm_configured():
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                brief = {
                    "definition": [x for x in [wiki_summary.split("\n")[0] if wiki_summary else ""] if x],
                    "key_points": [x for x in [web_summary] if x],
                    "conditions_and_boundaries": [],
                    "common_misconceptions": [],
                    "applications": [],
                    "derivation_or_proof_sketch": [],
                    "notes": ["（LLM 未配置：source_brief 为启发式兜底，建议配置模型以提升质量。）"],
                }
                ctx.working_memory.setdefault("source_briefs", {})[kp] = brief
                ctx.working_memory.setdefault("source_facts", {})[kp] = []
                return {
                    "knowledge_point": kp,
                    "source": "heuristic",
                    "source_brief": brief,
                    "facts": [],
                    "sources_used": len(sources),
                }

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "sources": sources,
                "requirements": [
                    "Synthesize sources into a writer-ready source brief. Goals: denoise, capture key points, and reduce downstream writing prompt length.",
                    "Do not copy source text verbatim. Rewrite and summarize in your own words.",
                    "Output strict JSON only. Do not output Markdown or extra explanation.",
                    "Organize the brief field by dimensions: definition, core_ideas, key_properties, conditions_and_boundaries, common_misconceptions, applications, derivation_or_proof_sketch, notation_and_terms.",
                    "The facts field is a list of key facts: {fact, confidence(0~1), source_ids[]}. Choose source_ids from sources[].id.",
                    "When sources conflict, prefer those with higher `credibility` (range 0~1; ≥0.8 is highly authoritative). Treat sources flagged with `pdf_unreadable` or other low-quality flags as last-resort hints only.",
                ],
                "schema": {
                    "knowledge_point": "string",
                    "brief": {
                        "definition": ["string"],
                        "core_ideas": ["string"],
                        "key_properties": ["string"],
                        "conditions_and_boundaries": ["string"],
                        "common_misconceptions": ["string"],
                        "applications": ["string"],
                        "derivation_or_proof_sketch": ["string"],
                        "notation_and_terms": ["string"],
                    },
                    "facts": [{"fact": "string", "confidence": 0.8, "source_ids": ["web:0"]}],
                    "missing": ["string"],
                },
            }

            raw = await self._call_llm_text(  # type: ignore[attr-defined]
                messages=[
                    {"role": "system", "content": _source_synthesis_system_prompt()},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.15,
                max_tokens=2200,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(raw)  # type: ignore[attr-defined]
            brief_obj = obj.get("brief") if isinstance(obj, dict) else None
            facts_obj = obj.get("facts") if isinstance(obj, dict) else None
            if not isinstance(brief_obj, dict):
                brief_obj = {}
            if not isinstance(facts_obj, list):
                facts_obj = []

            brief = {
                "definition": [str(x).strip() for x in (brief_obj.get("definition") or []) if str(x).strip()][:8],
                "core_ideas": [str(x).strip() for x in (brief_obj.get("core_ideas") or []) if str(x).strip()][:10],
                "key_properties": [str(x).strip() for x in (brief_obj.get("key_properties") or []) if str(x).strip()][
                    :12
                ],
                "conditions_and_boundaries": [
                    str(x).strip() for x in (brief_obj.get("conditions_and_boundaries") or []) if str(x).strip()
                ][:10],
                "common_misconceptions": [
                    str(x).strip() for x in (brief_obj.get("common_misconceptions") or []) if str(x).strip()
                ][:10],
                "applications": [str(x).strip() for x in (brief_obj.get("applications") or []) if str(x).strip()][:10],
                "derivation_or_proof_sketch": [
                    str(x).strip() for x in (brief_obj.get("derivation_or_proof_sketch") or []) if str(x).strip()
                ][:10],
                "notation_and_terms": [
                    str(x).strip() for x in (brief_obj.get("notation_and_terms") or []) if str(x).strip()
                ][:10],
            }

            cleaned_facts: List[Dict[str, Any]] = []
            for f in facts_obj[:24]:
                if not isinstance(f, dict):
                    continue
                fact = str(f.get("fact") or "").strip()
                if not fact:
                    continue
                try:
                    conf = float(f.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    conf = 0.0
                src_ids = f.get("source_ids")
                src_ids = [str(x).strip() for x in src_ids if str(x).strip()] if isinstance(src_ids, list) else []
                cleaned_facts.append({"fact": fact, "confidence": max(0.0, min(conf, 1.0)), "source_ids": src_ids[:6]})

            ctx.working_memory.setdefault("source_briefs", {})[kp] = brief
            ctx.working_memory.setdefault("source_facts", {})[kp] = cleaned_facts
            return {
                "knowledge_point": kp,
                "source": "llm",
                "source_brief": brief,
                "facts": cleaned_facts,
                "sources_used": len(sources),
            }

        items = [await _synthesize_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "items": items}
