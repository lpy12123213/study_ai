from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from backend.agent.types import CompressedContext


class StudyArchiveToolsMixin:
    async def _tool_assemble_study_archive(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将生成内容组装为最终自学档案 Markdown。"""

        material = ctx.working_memory.get("generate_study_material")
        if not isinstance(material, dict):
            material = (
                ctx.working_memory.get("study_material")
                if isinstance(ctx.working_memory.get("study_material"), dict)
                else {}
            )

        topic = str(args.get("topic") or material.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or material.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        preset = str(args.get("preset") or material.get("preset") or "").strip().lower()
        if preset and preset not in {"quick", "standard", "deep", "research"}:
            preset = ""
        requirements = str(args.get("requirements") or material.get("requirements") or "").strip()
        if len(requirements) > 160:
            requirements = requirements[:159].rstrip() + "…"
        sections = material.get("sections") if isinstance(material.get("sections"), list) else []

        # Preserve the split order as the final output order (parallel subagents may finish out-of-order).
        split_res = ctx.working_memory.get("split_knowledge_points")
        preferred_order: List[str] = []
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            preferred_order = [
                str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()
            ][:20]

        if preferred_order and sections:
            preferred_set = set(preferred_order)
            by_kp: Dict[str, List[Dict[str, Any]]] = {}
            rest: List[Dict[str, Any]] = []
            for sec in sections:
                if not isinstance(sec, dict):
                    continue
                kp = str(sec.get("knowledge_point") or "").strip()
                if not kp:
                    continue
                if kp in preferred_set:
                    by_kp.setdefault(kp, []).append(sec)
                else:
                    rest.append(sec)

            ordered: List[Dict[str, Any]] = []
            for kp in preferred_order:
                ordered.extend(by_kp.get(kp) or [])
            ordered.extend(rest)
            sections = ordered

        def _link(title: str, url: str) -> str:
            t = (title or "").strip()
            u = (url or "").strip()
            if t and u:
                return f"[{t}]({u})"
            return t or u

        refs_by_kp: Dict[str, List[Dict[str, str]]] = {}
        refs_seen_by_kp: Dict[str, set] = {}

        def _add_ref(*, kp: str, url: str, title: str, source: str) -> None:
            kp_key = (kp or "").strip()
            u = (url or "").strip()
            if not kp_key or not u:
                return
            key = u.split("#")[0].rstrip("/")
            seen = refs_seen_by_kp.setdefault(kp_key, set())
            if key in seen:
                return
            seen.add(key)
            t = (title or "").strip() or u
            s = (source or "").strip() or "web"
            refs_by_kp.setdefault(kp_key, []).append({"url": u, "title": t, "source": s})

        lines: List[str] = []
        lines.append(f"# 自学材料：{topic}")
        meta_lines: List[str] = []
        if subject:
            meta_lines.append(f"> 学科：{subject}")
        if preset:
            meta_lines.append(f"> 生成预设：{preset}")
        if requirements:
            meta_lines.append(f"> 额外要求：{requirements}")
        if meta_lines:
            lines.append("")
            lines.extend(meta_lines)
            lines.append("")

        lines.append("## 使用方式（建议）")
        lines.append("- 先按「知识点目录」顺序学习；每个知识点优先阅读「核心讲解」。")
        lines.append("- 资料来自多轮检索与聚合；建议先读讲解，再按需回查原始材料。")
        lines.append("")

        # Knowledge points list
        lines.append("## 知识点目录")
        kp_list = [
            str(s.get("knowledge_point") or "").strip()
            for s in sections
            if isinstance(s, dict) and str(s.get("knowledge_point") or "").strip()
        ]
        if kp_list:
            for kp in kp_list:
                lines.append(f"- {kp}")
        else:
            lines.append(f"- {topic}")
        lines.append("")

        for idx, sec in enumerate([s for s in sections if isinstance(s, dict)], start=1):
            kp = str(sec.get("knowledge_point") or "").strip()
            if not kp:
                continue
            num = str(idx)
            lines.append(f"## {num}、{kp}")
            lines.append("")

            # 核心讲解（优先展示“AI生成”的部分）
            lines.append("### 核心讲解")
            lines.append("")
            diagram_blob = sec.get("diagram") if isinstance(sec.get("diagram"), dict) else {}
            diagram_md = str(diagram_blob.get("markdown") or "").strip()
            diagram_caption = str(diagram_blob.get("caption") or "").strip()
            diagram_url = str(diagram_blob.get("url") or "").strip()

            diagrams_blob = ctx.working_memory.get("diagrams")
            extra_diagrams: List[Dict[str, Any]] = []
            if isinstance(diagrams_blob, dict):
                entries: List[Dict[str, Any]] = []
                if isinstance(diagrams_blob.get("items"), list):
                    entries = [x for x in (diagrams_blob.get("items") or []) if isinstance(x, dict)]
                elif isinstance(diagrams_blob.get("sections"), list):
                    entries = [x for x in (diagrams_blob.get("sections") or []) if isinstance(x, dict)]
                for it in entries:
                    if str(it.get("knowledge_point") or "").strip() != kp:
                        continue
                    ds = it.get("diagrams")
                    if isinstance(ds, list):
                        extra_diagrams = [d for d in ds if isinstance(d, dict)]
                    break

            extra_urls: set[str] = set()
            for d in extra_diagrams[:8]:
                md = str(d.get("markdown") or "").strip()
                if not md:
                    continue
                u = str(d.get("url") or "").strip()
                if u:
                    extra_urls.add(u)
                cap = str(d.get("caption") or "").strip()
                lines.append(md)
                if cap:
                    lines.append("")
                    lines.append(f"> 图注：{cap}")
                lines.append("")

            if diagram_md and (not diagram_url or diagram_url not in extra_urls):
                lines.append(diagram_md)
                if diagram_caption:
                    lines.append("")
                    lines.append(f"> 图注：{diagram_caption}")
                lines.append("")

            explanation = str(sec.get("explanation_markdown") or "").strip()
            lines.append(explanation or "（讲解为空：可能是模型调用失败或资料不足，建议重试或提供更具体的范围。）")
            explanation_source = str(sec.get("explanation_source") or "").strip()
            if explanation_source and explanation_source != "llm" and not explanation_source.lower().startswith("metaso"):
                lines.append("")
                lines.append(
                    f"> 注：本段讲解未成功使用模型生成（source={explanation_source}），已退回到摘要/兜底内容。若你已配置模型，请稍后重试或更换模型。"
                )
            lines.append("")

            # Collect references; they will be rendered once at the end as a bibliography.
            wiki = sec.get("wikipedia") if isinstance(sec.get("wikipedia"), dict) else {}
            mw = sec.get("mediawiki") if isinstance(sec.get("mediawiki"), dict) else {}
            wiki_title = str(wiki.get("title") or "").strip()
            wiki_url = str(wiki.get("url") or "").strip()
            mw_title = str(mw.get("title") or "").strip()
            mw_url = str(mw.get("url") or "").strip()
            if wiki_url:
                _add_ref(kp=kp, url=wiki_url, title=wiki_title or "词条", source="Wikipedia")
            if mw_url:
                _add_ref(kp=kp, url=mw_url, title=mw_title or "词条", source="MediaWiki")

            web_provider = str(sec.get("web_provider") or "").strip()
            web_source = f"网页检索/{web_provider}" if web_provider else "网页检索"
            web_results = sec.get("web_results") if isinstance(sec.get("web_results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:8]
            for r in web_results:
                title = str(r.get("title") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "网页", source=web_source)

            web_pages = sec.get("web_pages") if isinstance(sec.get("web_pages"), list) else []
            web_pages = [p for p in web_pages if isinstance(p, dict)][:6]
            for p in web_pages:
                title = str(p.get("title") or "").strip()
                url = str(p.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "网页正文", source="网页正文")

            se = sec.get("stackexchange") if isinstance(sec.get("stackexchange"), dict) else {}
            se_results = se.get("results") if isinstance(se.get("results"), list) else []
            se_results = [r for r in se_results if isinstance(r, dict)][:6]
            for r in se_results:
                title = str(r.get("title") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "问答", source="StackExchange")

            gh = sec.get("github") if isinstance(sec.get("github"), dict) else {}
            gh_results = gh.get("results") if isinstance(gh.get("results"), list) else []
            gh_results = [r for r in gh_results if isinstance(r, dict)][:6]
            for r in gh_results:
                full_name = str(r.get("full_name") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=full_name or "repo", source="GitHub")

        lines.append("---")
        lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return {
            "topic": topic,
            "subject": subject,
            "knowledge_points": kp_list[:20] if kp_list else ([topic] if topic else []),
            "markdown_chars": len(markdown),
        }

