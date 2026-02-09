from __future__ import annotations

import json
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, PlanStep, StepResult
from backend.crawler_manager import get_crawler
from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
)


class Executor:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def execute_step(self, step: PlanStep, *, context: CompressedContext) -> StepResult:
        tool = (step.tool or "").strip()
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return StepResult(step_id=step.id, tool=tool, success=False, error=f"Unknown tool: {tool}")

        try:
            output = await handler(step.arguments or {}, context)
            return StepResult(step_id=step.id, tool=tool, success=True, output=output)
        except Exception as exc:  # pragma: no cover (best-effort safety)
            return StepResult(step_id=step.id, tool=tool, success=False, error=str(exc))

    async def _call_llm_text(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
    ) -> str:
        if not LESSON_PLAN_API_KEY:
            return ""
        headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=float(API_TIMEOUT or 120)) as client:
            resp = await client.post(
                f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except Exception:
            return ""

    def _extract_json_obj(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}
        # Strip markdown code fences.
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _pick_questions(self, questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        cleaned: List[Tuple[int, Dict[str, Any]]] = []
        for q in questions:
            stem = str(q.get("stem") or "")
            if not stem or len(stem) < 8:
                continue
            # Prefer fewer images and reasonable length.
            penalty = 0
            penalty += stem.count("[图片:") * 50
            penalty += max(0, len(stem) - 500) // 20
            cleaned.append((penalty, q))
        cleaned.sort(key=lambda x: x[0])
        return [q for _, q in cleaned[: max(1, limit)]]

    async def _tool_split_knowledge_points(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将主题拆分为多个可检索的子知识点。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        min_points = int(args.get("min_points") or 3)
        max_points = int(args.get("max_points") or 8)
        min_points = max(1, min(min_points, 10))
        max_points = max(min_points, min(max_points, 15))

        def _clean_points(items: List[Any]) -> List[str]:
            out: List[str] = []
            seen: set[str] = set()
            for it in items or []:
                s = str(it or "").strip()
                s = re.sub(r"\s+", " ", s)
                s = s.strip(" -—·•\t\r\n")
                if not s:
                    continue
                if len(s) > 60:
                    s = s[:60].rstrip() + "…"
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
                if len(out) >= max_points:
                    break
            return out

        def _extract_wiki_headings(content: str) -> List[str]:
            if not content:
                return []
            # Wikipedia plaintext headings often look like: "== 标题 ==" or "=== 标题 ==="
            headings = re.findall(r"^==+\s*(.+?)\s*==+\s*$", content, flags=re.MULTILINE)
            cleaned: List[str] = []
            stop_exact = {
                "参见",
                "参考文献",
                "外部链接",
                "注释",
                "延伸阅读",
                "参考资料",
                "脚注",
            }
            stop_contains = ["参考", "链接", "注释"]
            for h in headings:
                s = str(h or "").strip()
                s = re.sub(r"\s+", " ", s)
                s = re.sub(r"[（(].*?[）)]", "", s).strip()
                if not s:
                    continue
                if s in stop_exact:
                    continue
                if any(x in s for x in stop_contains):
                    continue
                if len(s) < 2 or len(s) > 24:
                    continue
                cleaned.append(s)
            return cleaned

        async def _split_from_wikipedia() -> List[str]:
            """Best-effort: use Wikipedia page structure to derive sub-knowledge points."""
            try:
                from backend.mcp.wikipedia_search import wikipedia_search as _wiki
            except Exception:
                return []

            q = topic
            # Provide a small disambiguation hint for math topics.
            if subject and "数学" in subject and "数学" not in q:
                q = f"{q} 数学"
            try:
                res = await _wiki(
                    query=q,
                    lang="zh",
                    sentences=2,
                    auto_suggest=True,
                    search_results=5,
                    max_content_length=5000,
                )
            except Exception:
                return []

            if not isinstance(res, dict) or not res.get("success"):
                return []

            content = str(res.get("content") or "")
            headings = _extract_wiki_headings(content)
            hits = res.get("search_hits") if isinstance(res.get("search_hits"), list) else []
            hits = [str(x or "").strip() for x in hits if str(x or "").strip()]

            generic_headings = {"概述", "定义", "性质", "定理", "方法", "应用", "相关概念", "基本概念"}
            candidates: List[str] = []
            for h in headings:
                if h in generic_headings:
                    candidates.append(f"{topic} {h}")
                else:
                    candidates.append(h)
            # Prefer a few related search hits (often include key terms).
            candidates.extend(hits[:8])
            return _clean_points(candidates)

        def _split_by_templates() -> List[str]:
            """Domain heuristics for common topics when no LLM is configured."""
            t = topic
            cands: List[str] = []

            # Projective geometry (射影几何 / 射影)
            if "射影" in t:
                cands.extend(
                    [
                        "射影空间",
                        "齐次坐标",
                        "射影变换",
                        "交比（射影不变量）",
                        "对偶原理",
                        "德萨格定理",
                        "帕普斯定理",
                        "消失点与透视投影",
                        "圆锥曲线的射影性质",
                    ]
                )

            # Generic math fallbacks (still searchable)
            if ("数学" in subject) or ("几何" in t) or ("代数" in t) or ("函数" in t):
                cands.extend(
                    [
                        f"{t} 基本概念",
                        f"{t} 典型性质",
                        f"{t} 常见题型",
                        f"{t} 易错点",
                    ]
                )
            return _clean_points(cands)

        # LLM-powered split when configured.
        if LESSON_PLAN_API_KEY:
            prompt = {
                "topic": topic,
                "subject": subject,
                "instructions": (
                    "请把 topic 拆分为若干个可用于检索的子知识点（短语级关键词）。\n"
                    f"- 数量：{min_points} 到 {max_points} 个\n"
                    "- 每个子知识点尽量具体、互不重复\n"
                    "- 仅输出严格 JSON（不要 Markdown、不要代码块）\n"
                    '- JSON 格式：{"knowledge_points": ["...", "..."]}\n'
                ),
            }
            text = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=self.config.planner_model,
                temperature=0.2,
                max_tokens=600,
            )
            obj = self._extract_json_obj(text)
            points = _clean_points(list(obj.get("knowledge_points") or []))
            if len(points) >= min_points:
                return {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_points": points,
                    "source": "llm",
                }

        # Heuristic fallback: split by punctuation if user provided a list.
        raw = re.split(r"[\n,，;；、/|]+", topic)
        points = _clean_points([x for x in raw if str(x).strip()])

        # If still too few points (single concept), try Wikipedia headings + templates.
        if len(points) < min_points:
            wiki_points = await _split_from_wikipedia()
            points = _clean_points(points + wiki_points)

        if len(points) < min_points:
            tpl_points = _split_by_templates()
            points = _clean_points(points + tpl_points)

        if not points and topic:
            points = [topic]

        # Ensure at least min_points when possible (pad with safe variants).
        if topic and len(points) < min_points:
            pads = [topic]
            pads.extend([f"{topic} 基本概念", f"{topic} 常见题型", f"{topic} 典型例题"])
            points = _clean_points(points + pads)

        return {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points or ([topic] if topic else []),
            "source": "heuristic+",
            "note": "未配置拆分模型或拆分不足，使用 Wikipedia 结构 + 规则模板增强拆分。",
        }

    async def _tool_web_search_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """网络搜索知识点：Exa 优先，智谱 BigModel 兜底。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        text_max_length = int(args.get("text_max_length") or 2600)
        text_max_length = max(200, min(text_max_length, 8000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.exa_web_search import exa_search
        from backend.mcp.bigmodel_web_search import web_search_with_bigmodel_mcp

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            # 1) Exa
            exa = await exa_search(
                query=query,
                num_results=limit,
                use_autoprompt=True,
                type="neural",
                include_text=True,
                text_max_length=text_max_length,
            )
            exa_results = exa.get("results") if isinstance(exa, dict) else []
            if isinstance(exa_results, list) and exa_results:
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "exa",
                    "results": exa_results,
                    "autoprompt_string": exa.get("autoprompt_string") if isinstance(exa, dict) else None,
                }

            # 2) BigModel MCP broker fallback
            zhipu = await web_search_with_bigmodel_mcp(query=query, limit=limit)
            if isinstance(zhipu, dict) and zhipu.get("success") and zhipu.get("results"):
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": str(zhipu.get("provider") or "zhipu-bigmodel-mcp-web-search"),
                    "results": zhipu.get("results") or [],
                }

            # 3) Both failed
            return {
                "knowledge_point": point,
                "base_query": base_query,
                "query": query,
                "queries": [query],
                "provider": "none",
                "results": [],
                "error": (exa.get("error") if isinstance(exa, dict) and exa.get("error") else "")
                or (zhipu.get("error") if isinstance(zhipu, dict) and zhipu.get("error") else "web search failed"),
            }

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "query": point,
                        "provider": "none",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "text_max_length": text_max_length,
            "items": items,
        }

    async def _tool_github_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """GitHub 搜索：为每个知识点检索可能的高质量笔记/资料仓库。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        sort = str(args.get("sort") or "stars").strip() or "stars"
        order = str(args.get("order") or "desc").strip() or "desc"
        include_readme = bool(args.get("include_readme", False))
        readme_limit = int(args.get("readme_limit") or (2 if include_readme else 0))
        readme_limit = max(0, min(readme_limit, 3))
        readme_max_chars = int(args.get("readme_max_chars") or 3000)
        readme_max_chars = max(200, min(readme_max_chars, 10000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.github_search import github_fetch_readme, github_search_repositories

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            # Bias toward repositories with documentation.
            gh_query = f"{query} in:readme"
            res = await github_search_repositories(gh_query, limit=limit, sort=sort, order=order)
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": gh_query,
                    "provider": "github",
                    "results": [],
                    "error": str((res or {}).get("error") or "github search failed"),
                    "note": str((res or {}).get("note") or ""),
                }

            results = res.get("results") or []
            if include_readme and readme_limit > 0 and isinstance(results, list) and results:
                enriched: List[Dict[str, Any]] = []
                for r in results:
                    enriched.append(r if isinstance(r, dict) else {})
                for r in enriched[:readme_limit]:
                    full_name = str(r.get("full_name") or "").strip()
                    if not full_name:
                        continue
                    rd = await github_fetch_readme(full_name, max_chars=readme_max_chars)
                    if isinstance(rd, dict) and rd.get("success") and rd.get("readme"):
                        r["readme_excerpt"] = str(rd.get("readme") or "")
                results = enriched

            out: Dict[str, Any] = {
                "knowledge_point": point,
                "success": True,
                "query": gh_query,
                "queries": [gh_query],
                "provider": "github",
                "results": results,
                "total_count": res.get("total_count") or 0,
            }
            note = str(res.get("note") or "").strip()
            if note:
                out["note"] = note
            return out

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "provider": "github",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }

    async def _tool_stackexchange_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """StackExchange 搜索：为每个知识点检索高质量问答解释。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        site = str(args.get("site") or "math.stackexchange").strip() or "math.stackexchange"
        include_answers = bool(args.get("include_answers", True))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.stackexchange_search import stackexchange_search

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            res = await stackexchange_search(
                query=query,
                site=site,
                limit=limit,
                include_answers=include_answers,
                max_question_chars=3200,
                max_answer_chars=3200,
            )
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": query,
                    "site": site,
                    "provider": "stackexchange",
                    "results": [],
                    "error": str((res or {}).get("error") or "stackexchange search failed"),
                }
            return {
                "knowledge_point": point,
                "success": True,
                "query": query,
                "queries": [query],
                "site": site,
                "provider": "stackexchange",
                "results": res.get("results") or [],
            }

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "site": site,
                        "provider": "stackexchange",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "site": site,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }

    async def _tool_mediawiki_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """MediaWiki 百科检索（可用于 Wikipedia/Wikibooks/ProofWiki 等 MediaWiki 站点）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        # Base URL building:
        # - if base_url provided: use it directly
        # - else: build from project + lang, e.g. https://zh.wikibooks.org/
        base_url = str(args.get("base_url") or "").strip()
        project = str(args.get("project") or "").strip().lower()
        lang = str(args.get("lang") or "zh").strip() or "zh"

        if not base_url:
            if project in {"wikipedia", "wikibooks", "wikiversity", "wikisource", "wiktionary"}:
                domain = "wikipedia.org" if project == "wikipedia" else f"{project}.org"
                base_url = f"https://{lang}.{domain}/"
            elif project:
                base_url = str(project)

        sentences = int(args.get("sentences") or 5)
        sentences = max(1, min(sentences, 10))
        search_results = int(args.get("search_results") or 5)
        search_results = max(1, min(search_results, 10))
        max_content_length = int(args.get("max_content_length") or 6000)
        max_content_length = max(200, min(max_content_length, 8000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.mediawiki_search import mediawiki_search

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            res = await mediawiki_search(
                query=query,
                base_url=base_url,
                sentences=sentences,
                search_results=search_results,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid mediawiki response"}
            payload["knowledge_point"] = point
            payload["provider"] = payload.get("provider") or "mediawiki_api"
            return payload

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _lookup_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "success": False,
                        "knowledge_point": point,
                        "query": point,
                        "error": str(exc),
                        "provider": "mediawiki_api",
                        "base_url": base_url,
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "base_url": base_url,
            "project": project,
            "lang": lang,
            "sentences": sentences,
            "search_results": search_results,
            "max_content_length": max_content_length,
            "items": items,
        }

    async def _tool_browse_web_pages(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Browse and extract readable text from top web-search results for each knowledge point.

        Best-effort "browseuse" behavior:
        - Uses prior `web_search_knowledge` outputs in working_memory to pick URLs
        - Fetches pages via httpx and extracts visible text using BeautifulSoup
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        top_k = int(args.get("top_k") or 2)
        top_k = max(1, min(top_k, 5))
        max_chars = int(args.get("max_chars") or 8000)
        max_chars = max(800, min(max_chars, 30000))
        timeout_s = float(args.get("timeout_s") or 18)
        timeout_s = max(5.0, min(timeout_s, 60.0))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        def _map_by_point(blob: Any) -> Dict[str, Dict[str, Any]]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Dict[str, Any]] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        mapped[kp] = it
                return mapped
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}  # type: ignore[return-value]
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))

        def _extract_urls(results: Any) -> List[str]:
            if not isinstance(results, list):
                return []
            urls: List[str] = []
            seen: set[str] = set()
            for r in results:
                if not isinstance(r, dict):
                    continue
                u = str(r.get("url") or r.get("link") or "").strip()
                if not u or not u.startswith(("http://", "https://")):
                    continue
                key = u.lower()
                if key in seen:
                    continue
                seen.add(key)
                urls.append(u)
                if len(urls) >= max(10, top_k * 3):
                    break
            return urls

        def _normalize_url_for_fetch(u: str) -> str:
            raw = (u or "").strip()
            if not raw:
                return ""
            try:
                parsed = urlparse(raw)
                host = (parsed.netloc or "").lower()
                if host == "link.zhihu.com":
                    qs = parse_qs(parsed.query or "")
                    target = qs.get("target", [""])[0]
                    if target:
                        return unquote(str(target))
                return raw
            except Exception:
                return raw

        def _is_zhihu_url(u: str) -> bool:
            try:
                host = (urlparse(u).netloc or "").lower()
            except Exception:
                return False
            return host == "zhihu.com" or host.endswith(".zhihu.com")

        async def _fetch_one(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            url = _normalize_url_for_fetch(url) or url

            if _is_zhihu_url(url):
                cookies = (os.getenv("ZHIHU_COOKIES") or "").strip()
                try:
                    from backend.mcp.zhihu_fetcher import ZhihuFetcher
                except Exception as exc:
                    return {"url": url, "success": False, "error": f"zhihu_fetcher not available: {exc}"}

                try:
                    zh_timeout = int(max(5.0, min(float(timeout_s), 60.0)))
                except Exception:
                    zh_timeout = 30

                fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=zh_timeout)
                res = await fetcher.fetch(url)
                payload = res.to_dict()

                if not bool(payload.get("success")):
                    out: Dict[str, Any] = {
                        "url": url,
                        "success": False,
                        "provider": "zhihu",
                        "error": str(payload.get("error") or "fetch_failed"),
                        "title": str(payload.get("title") or "").strip(),
                        "author": str(payload.get("author") or "").strip(),
                        "date": str(payload.get("date") or "").strip(),
                        "zhihu_type": str(payload.get("type") or "").strip(),
                    }
                    out = {k: v for k, v in out.items() if v not in ("", None)}
                    if out.get("error") == "cookies_required" and not cookies:
                        out["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES"
                    return out

                text = str(payload.get("content_markdown") or "").strip()
                if len(text) > max_chars:
                    text = text[: max_chars - 1].rstrip() + "…"

                out = {
                    "url": url,
                    "success": True,
                    "provider": "zhihu",
                    "content_type": "text/markdown",
                    "zhihu_type": str(payload.get("type") or "").strip(),
                    "title": str(payload.get("title") or "").strip(),
                    "author": str(payload.get("author") or "").strip(),
                    "date": str(payload.get("date") or "").strip(),
                    "chars": len(text),
                    "text": text,
                }
                return {k: v for k, v in out.items() if v not in ("", None)}

            # Skip non-HTML-ish resources.
            if url.lower().endswith((".pdf", ".zip", ".rar", ".7z")):
                return {"url": url, "success": False, "error": "unsupported file type"}
            try:
                resp = await client.get(url)
                ct = str(resp.headers.get("content-type") or "").lower()
                if "application/pdf" in ct:
                    return {"url": url, "success": False, "error": "pdf not supported", "content_type": ct}
                html = resp.text or ""
            except Exception as exc:
                return {"url": url, "success": False, "error": str(exc)}

            try:
                from bs4 import BeautifulSoup  # type: ignore
            except Exception as exc:
                return {"url": url, "success": False, "error": f"beautifulsoup4 not available: {exc}"}

            try:
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "noscript", "svg"]):
                    try:
                        tag.decompose()
                    except Exception:
                        pass
                for tag in soup(["header", "footer", "nav", "aside"]):
                    try:
                        tag.decompose()
                    except Exception:
                        pass

                title = ""
                try:
                    title = str(soup.title.string or "").strip() if soup.title else ""
                except Exception:
                    title = ""

                extracted = soup.get_text("\n", strip=True)
                extracted = re.sub(r"\n{3,}", "\n\n", extracted).strip()
                if len(extracted) > max_chars:
                    extracted = extracted[: max_chars - 1].rstrip() + "…"

                return {
                    "url": url,
                    "success": True,
                    "title": title,
                    "content_type": ct,
                    "chars": len(extracted),
                    "text": extracted,
                }
            except Exception as exc:
                return {"url": url, "success": False, "error": f"parse failed: {exc}"}

        concurrency = int(args.get("concurrency") or 2)
        concurrency = max(1, min(concurrency, 4))
        sem = asyncio.Semaphore(concurrency)
        zhihu_sem = asyncio.Semaphore(min(2, concurrency))

        async def _guarded_fetch(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            normalized = _normalize_url_for_fetch(url) or url
            async with sem:
                if _is_zhihu_url(normalized):
                    async with zhihu_sem:
                        return await _fetch_one(normalized, client=client)
                return await _fetch_one(normalized, client=client)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        items: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout_s, headers=headers, follow_redirects=True) as client:
            for point in points:
                web = web_map.get(point) or {}
                urls = _extract_urls(web.get("results"))
                urls = urls[: max(0, top_k)]

                if not urls:
                    items.append(
                        {
                            "knowledge_point": point,
                            "success": False,
                            "top_k": top_k,
                            "max_chars": max_chars,
                            "pages": [],
                            "error": "no urls from web_search_knowledge",
                        }
                    )
                    continue

                pages = await asyncio.gather(*[_guarded_fetch(u, client=client) for u in urls])
                ok = [p for p in pages if isinstance(p, dict) and p.get("success")]
                items.append(
                    {
                        "knowledge_point": point,
                        "success": len(ok) > 0,
                        "top_k": top_k,
                        "max_chars": max_chars,
                        "source": "web_search_knowledge",
                        "pages": pages,
                    }
                )

        return {"topic": topic, "subject": subject, "top_k": top_k, "max_chars": max_chars, "items": items}

    async def _tool_wikipedia_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Wikipedia 百科检索（按拆分后的知识点批量查询）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        lang = str(args.get("lang") or "zh").strip() or "zh"
        sentences = int(args.get("sentences") or 4)
        sentences = max(1, min(sentences, 10))
        max_content_length = int(args.get("max_content_length") or 2000)
        max_content_length = max(200, min(max_content_length, 8000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.wikipedia_search import wikipedia_search as _wiki

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            res = await _wiki(
                query=query,
                lang=lang,
                sentences=sentences,
                auto_suggest=True,
                search_results=5,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid wikipedia response"}
            payload = dict(payload)
            payload["knowledge_point"] = point
            payload["query"] = query
            return payload

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _lookup_one(point)
                except Exception as exc:  # pragma: no cover
                    return {"success": False, "knowledge_point": point, "query": point, "error": str(exc), "provider": "wikipedia"}

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {"topic": topic, "subject": subject, "lang": lang, "items": items}

    async def _tool_search_questions_by_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """题库检索：按拆分后的知识点批量搜索例题与练习题。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip() or "中等"
        examples_limit = int(args.get("examples_limit") or 1)
        exercises_limit = int(args.get("exercises_limit") or 4)
        examples_limit = max(0, min(examples_limit, 3))
        exercises_limit = max(0, min(exercises_limit, 10))
        max_pages = int(args.get("max_pages") or 2)
        max_pages = max(1, min(max_pages, 3))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        crawler = await get_crawler(subject=subject)
        applied_subject = subject or getattr(crawler, "subject", "")

        items: List[Dict[str, Any]] = []
        for point in points:
            fetch_limit = int(args.get("limit") or 0) or max(18, (examples_limit + exercises_limit) * 4)
            fetch_limit = max(10, min(fetch_limit, 60))
            try:
                res = await crawler.search_by_knowledge(
                    knowledge_point=point,
                    subject=applied_subject,
                    limit=fetch_limit,
                    difficulty=difficulty,
                    max_pages=max_pages,
                    dedup_by_stem=True,
                    min_quality_score=10,
                    with_quality=True,
                    strict_subject=True,
                    require_difficulty=True,
                )
                questions = list(res.get("questions") or []) if isinstance(res, dict) else []
                examples = self._pick_questions(questions, limit=max(1, examples_limit)) if examples_limit else []
                used_ids = {str(q.get("question_id") or "").strip() for q in examples if isinstance(q, dict)}
                remaining = [
                    q
                    for q in questions
                    if isinstance(q, dict) and str(q.get("question_id") or "").strip() and str(q.get("question_id") or "").strip() not in used_ids
                ]
                exercises = self._pick_questions(remaining, limit=max(1, exercises_limit)) if exercises_limit else []
                items.append(
                    {
                        "knowledge_point": point,
                        "success": bool(res.get("success")) if isinstance(res, dict) and "success" in res else True,
                        "difficulty": difficulty,
                        "examples": examples[:examples_limit] if examples_limit else [],
                        "exercises": exercises[:exercises_limit] if exercises_limit else [],
                        "raw_count": len(questions),
                        "provider": "question-bank",
                    }
                )
            except Exception as exc:  # pragma: no cover
                items.append(
                    {
                        "knowledge_point": point,
                        "success": False,
                        "difficulty": difficulty,
                        "examples": [],
                        "exercises": [],
                        "raw_count": 0,
                        "provider": "question-bank",
                        "error": str(exc),
                    }
                )

        return {
            "topic": topic,
            "subject": applied_subject,
            "difficulty": difficulty,
            "examples_limit": examples_limit,
            "exercises_limit": exercises_limit,
            "items": items,
        }

    async def _tool_generate_study_material(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """基于聚合数据，为每个知识点生成讲解与例题解答。"""

        aggregated = ctx.working_memory.get("aggregate_knowledge") or ctx.working_memory.get("aggregated")
        if not isinstance(aggregated, dict):
            aggregated = {}

        topic = str(args.get("topic") or aggregated.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or aggregated.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        sections_in = aggregated.get("items") if isinstance(aggregated.get("items"), list) else []

        # Optional: generate only for specified knowledge points (useful when running per-point subagents).
        requested_points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            requested_points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if requested_points:
            requested_set = {p for p in requested_points}
            sections_in = [
                it
                for it in (sections_in or [])
                if isinstance(it, dict) and str(it.get("knowledge_point") or "").strip() in requested_set
            ]

        max_points = int(args.get("max_points") or 8)
        max_points = max(1, min(max_points, 15))
        max_examples = int(args.get("max_examples") or 1)
        max_examples = max(0, min(max_examples, 2))
        max_web_results = int(args.get("max_web_results") or 8)
        max_web_results = max(3, min(max_web_results, 15))
        max_web_pages = int(args.get("max_web_pages") or 2)
        max_web_pages = max(0, min(max_web_pages, 4))
        max_page_chars = int(args.get("max_page_chars") or 3200)
        max_page_chars = max(500, min(max_page_chars, 8000))

        sections: List[Dict[str, Any]] = []
        for item in (sections_in or [])[:max_points]:
            if not isinstance(item, dict):
                continue
            kp = str(item.get("knowledge_point") or "").strip()
            if not kp:
                continue

            wiki = item.get("wikipedia") if isinstance(item.get("wikipedia"), dict) else {}
            mw = item.get("mediawiki") if isinstance(item.get("mediawiki"), dict) else {}
            web = item.get("web_search") if isinstance(item.get("web_search"), dict) else {}
            pages_blob = item.get("web_pages") if isinstance(item.get("web_pages"), dict) else {}
            gh = item.get("github") if isinstance(item.get("github"), dict) else {}
            se = item.get("stackexchange") if isinstance(item.get("stackexchange"), dict) else {}
            q = item.get("questions") if isinstance(item.get("questions"), dict) else {}

            web_results = web.get("results") if isinstance(web.get("results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:max_web_results]

            web_pages = pages_blob.get("pages") if isinstance(pages_blob.get("pages"), list) else []
            web_pages = [p for p in web_pages if isinstance(p, dict)]
            web_pages = [p for p in web_pages if p.get("success") and str(p.get("text") or "").strip()]
            web_pages = web_pages[:max_web_pages]

            examples = q.get("examples") if isinstance(q.get("examples"), list) else []
            exercises = q.get("exercises") if isinstance(q.get("exercises"), list) else []
            examples = [x for x in examples if isinstance(x, dict)][: max_examples or 0]
            exercises = [x for x in exercises if isinstance(x, dict)][:10]

            # Explanation (LLM if configured; fallback to Wikipedia summary)
            explanation_md = ""
            if LESSON_PLAN_API_KEY:
                def _clip_text(text: str, limit_chars: int) -> str:
                    t = (text or "").strip()
                    if len(t) <= limit_chars:
                        return t
                    return t[: limit_chars - 1].rstrip() + "…"

                payload = {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_point": kp,
                    "wikipedia": {
                        "title": wiki.get("title"),
                        "url": wiki.get("url"),
                        "summary": wiki.get("summary"),
                    },
                    "mediawiki": {
                        "title": mw.get("title"),
                        "url": mw.get("url"),
                        "summary": mw.get("summary"),
                        "base_url": mw.get("base_url"),
                    },
                    "web_results": [
                        {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("snippet") or r.get("text")}
                        for r in web_results
                    ],
                    "web_pages": [
                        {
                            "title": p.get("title"),
                            "url": p.get("url"),
                            "extract": _clip_text(str(p.get("text") or ""), max_page_chars),
                        }
                        for p in web_pages
                    ],
                    "github_repos": [
                        {
                            "full_name": r.get("full_name"),
                            "url": r.get("url"),
                            "description": r.get("description"),
                            "stars": r.get("stars"),
                            "language": r.get("language"),
                            "readme_excerpt": _clip_text(str(r.get("readme_excerpt") or ""), max_page_chars),
                        }
                        for r in (gh.get("results") if isinstance(gh.get("results"), list) else [])[:10]
                        if isinstance(r, dict)
                    ],
                    "stackexchange": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "score": r.get("score"),
                            "tags": r.get("tags"),
                            "question_text": _clip_text(str(r.get("question_text") or ""), max_page_chars),
                            "top_answer_text": _clip_text(str(r.get("top_answer_text") or ""), max_page_chars),
                        }
                        for r in (se.get("results") if isinstance(se.get("results"), list) else [])[:8]
                        if isinstance(r, dict)
                    ],
                    "instructions": (
                        "请生成该知识点的自学讲解（Markdown），包含：定义/直观理解/关键点/常见误区/方法小结。\n"
                        "尽量只依据给定的 wikipedia/mediawiki/web_results/web_pages/github/stackexchange 信息；若信息不足，请标注“推断/建议”。\n"
                        "不要输出例题或练习题。"
                    ),
                }
                explanation_md = (
                    await self._call_llm_text(
                        messages=[
                            {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        model=self.config.planner_model,
                        temperature=0.3,
                        max_tokens=900,
                    )
                ).strip()
            if not explanation_md:
                wiki_summary = str(wiki.get("summary") or "").strip()
                if wiki_summary:
                    explanation_md = f"**百科摘要**：{wiki_summary}\n"
                else:
                    mw_summary = str(mw.get("summary") or "").strip()
                    if mw_summary:
                        explanation_md = f"**MediaWiki 摘要**：{mw_summary}\n"
                    else:
                        explanation_md = "（未获取到可靠百科摘要；以下内容以题库练习与网络检索为主。）\n"

            # Example solutions
            solved_examples: List[Dict[str, Any]] = []
            for ex in examples:
                stem = str(ex.get("stem") or "").strip()
                if not stem:
                    continue
                sol_md = ""
                if LESSON_PLAN_API_KEY:
                    prompt = (
                        "请为下面例题写出详细分步解答（Markdown）。\n\n"
                        "要求：\n- 每一步说明在做什么\n- 结论清晰\n\n"
                        f"题目：\n{stem}\n"
                    )
                    sol_md = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的解题老师，输出必须是Markdown。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=self.config.planner_model,
                            temperature=0.3,
                            max_tokens=1100,
                        )
                    ).strip()
                if not sol_md:
                    sol_md = "（未配置模型，无法生成解答。）"
                solved_examples.append(
                    {
                        "question_id": ex.get("question_id"),
                        "stem": stem,
                        "solution_markdown": sol_md,
                        "difficulty": ex.get("difficulty"),
                        "source": ex.get("source"),
                    }
                )

            sections.append(
                {
                    "knowledge_point": kp,
                    "explanation_markdown": explanation_md,
                    "wikipedia": wiki,
                    "mediawiki": mw,
                    "web_results": web_results,
                    "web_pages": web_pages,
                    "github": gh,
                    "stackexchange": se,
                    "examples": solved_examples,
                    "exercises": exercises,
                }
            )

        # Merge with prior generated sections so per-knowledge-point runs can accumulate.
        previous = ctx.working_memory.get("generate_study_material") or ctx.working_memory.get("study_material")
        prev_sections = previous.get("sections") if isinstance(previous, dict) and isinstance(previous.get("sections"), list) else []

        merged_by_kp: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []

        for sec in prev_sections:
            if not isinstance(sec, dict):
                continue
            kp = str(sec.get("knowledge_point") or "").strip()
            if not kp:
                continue
            if kp not in order:
                order.append(kp)
            merged_by_kp[kp] = sec

        for sec in sections:
            if not isinstance(sec, dict):
                continue
            kp = str(sec.get("knowledge_point") or "").strip()
            if not kp:
                continue
            if kp not in order:
                order.append(kp)
            merged_by_kp[kp] = sec

        merged_sections = [merged_by_kp[kp] for kp in order if kp in merged_by_kp]
        out = {
            "topic": topic,
            "subject": subject,
            "sections": merged_sections,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        ctx.working_memory["study_material"] = out
        return out

    async def _tool_assemble_study_archive(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        """将生成内容组装为最终自学档案 Markdown。"""

        material = ctx.working_memory.get("generate_study_material")
        if not isinstance(material, dict):
            material = ctx.working_memory.get("study_material") if isinstance(ctx.working_memory.get("study_material"), dict) else {}

        topic = str(args.get("topic") or material.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or material.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        sections = material.get("sections") if isinstance(material.get("sections"), list) else []

        def _link(title: str, url: str) -> str:
            t = (title or "").strip()
            u = (url or "").strip()
            if t and u:
                return f"[{t}]({u})"
            return t or u

        chinese_nums = "一二三四五六七八九十"
        lines: List[str] = []
        lines.append(f"# 自学档案：{topic}")
        if subject:
            lines.append("")
            lines.append(f"> 学科：{subject}")
        lines.append("")

        # Knowledge points list
        lines.append("## 知识点拆分")
        kp_list = [str(s.get("knowledge_point") or "").strip() for s in sections if isinstance(s, dict) and str(s.get("knowledge_point") or "").strip()]
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
            num = chinese_nums[idx - 1] if 1 <= idx <= len(chinese_nums) else str(idx)
            lines.append(f"## {num}、{kp}")
            lines.append("")

            # 1.1 Wikipedia
            wiki = sec.get("wikipedia") if isinstance(sec.get("wikipedia"), dict) else {}
            mw = sec.get("mediawiki") if isinstance(sec.get("mediawiki"), dict) else {}
            lines.append("### 1.1 百科定义（Wikipedia / MediaWiki）")
            lines.append("")
            wiki_title = str(wiki.get("title") or "").strip()
            wiki_url = str(wiki.get("url") or "").strip()
            wiki_summary = str(wiki.get("summary") or "").strip()

            mw_title = str(mw.get("title") or "").strip()
            mw_url = str(mw.get("url") or "").strip()
            mw_summary = str(mw.get("summary") or "").strip()

            if wiki_title or wiki_url or wiki_summary:
                if wiki_title or wiki_url:
                    lines.append(f"- Wikipedia：{_link(wiki_title, wiki_url)}")
                if wiki_summary:
                    lines.append("")
                    lines.append(wiki_summary)
            if mw_title or mw_url or mw_summary:
                if mw_title or mw_url:
                    lines.append("")
                    lines.append(f"- MediaWiki：{_link(mw_title, mw_url)}")
                if mw_summary:
                    lines.append("")
                    lines.append(mw_summary)

            if not (wiki_title or wiki_url or wiki_summary or mw_title or mw_url or mw_summary):
                lines.append("（未检索到可靠百科词条）")
            lines.append("")

            # 1.2 Web
            lines.append("### 1.2 网络资料")
            lines.append("")
            web_results = sec.get("web_results") if isinstance(sec.get("web_results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:5]
            if web_results:
                for r in web_results:
                    title = str(r.get("title") or "").strip()
                    url = str(r.get("url") or "").strip()
                    snippet = str(r.get("snippet") or r.get("text") or "").strip()
                    line = f"- {_link(title, url)}"
                    if snippet:
                        line += f"：{snippet}"
                    lines.append(line)
            else:
                lines.append("（未检索到网络资料或未配置搜索 Key）")

            se = sec.get("stackexchange") if isinstance(sec.get("stackexchange"), dict) else {}
            se_results = se.get("results") if isinstance(se.get("results"), list) else []
            se_results = [r for r in se_results if isinstance(r, dict)][:3]
            if se_results:
                lines.append("")
                lines.append("**StackExchange（精选问答）**：")
                for r in se_results:
                    title = str(r.get("title") or "").strip()
                    url = str(r.get("url") or "").strip()
                    score = r.get("score")
                    suffix = f"（score={score}）" if isinstance(score, int) else ""
                    lines.append(f"- {_link(title, url)}{suffix}")

            gh = sec.get("github") if isinstance(sec.get("github"), dict) else {}
            gh_results = gh.get("results") if isinstance(gh.get("results"), list) else []
            gh_results = [r for r in gh_results if isinstance(r, dict)][:3]
            if gh_results:
                lines.append("")
                lines.append("**GitHub（可能有用的资料仓库）**：")
                for r in gh_results:
                    full_name = str(r.get("full_name") or "").strip()
                    url = str(r.get("url") or "").strip()
                    desc = str(r.get("description") or "").strip()
                    line = f"- {_link(full_name or 'repo', url)}"
                    if desc:
                        line += f"：{desc}"
                    lines.append(line)
            lines.append("")

            # 讲解
            lines.append("### 1.3 知识点讲解")
            lines.append("")
            explanation = str(sec.get("explanation_markdown") or "").strip()
            lines.append(explanation or "（讲解为空）")
            lines.append("")

            # 例题
            lines.append("### 1.4 例题精讲（含步骤）")
            lines.append("")
            examples = sec.get("examples") if isinstance(sec.get("examples"), list) else []
            examples = [e for e in examples if isinstance(e, dict)]
            if examples:
                for ex_i, ex in enumerate(examples, start=1):
                    lines.append(f"#### 例题 {ex_i}")
                    lines.append("")
                    stem = str(ex.get("stem") or "").strip()
                    sol = str(ex.get("solution_markdown") or "").strip()
                    if stem:
                        lines.append("**题目**：")
                        lines.append("")
                        lines.append(stem)
                        lines.append("")
                    if sol:
                        lines.append("**解答**：")
                        lines.append("")
                        lines.append(sol)
                        lines.append("")
            else:
                lines.append("（未检索到例题）")
                lines.append("")

            # 练习题
            lines.append("### 1.5 练习题（不含答案）")
            lines.append("")
            exercises = sec.get("exercises") if isinstance(sec.get("exercises"), list) else []
            exercises = [e for e in exercises if isinstance(e, dict)]
            if exercises:
                for ex_i, ex in enumerate(exercises, start=1):
                    stem = str(ex.get("stem") or "").strip()
                    if not stem:
                        continue
                    lines.append(f"{ex_i}. {stem}")
                    lines.append("")
            else:
                lines.append("（未检索到练习题）")
                lines.append("")

        lines.append("---")
        lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("数据来源：Wikipedia/MediaWiki、Exa/智谱联网搜索、StackExchange、GitHub、题库")
        lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return markdown

    async def _tool_aggregate_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """聚合：拆分结果 + Wikipedia + Web 搜索 + 题库检索。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        def _map_by_point(blob: Any) -> Dict[str, Any]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Any] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if not kp:
                        continue
                    mapped[kp] = it
                return mapped
            # Single-result style payload
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))
        browse_map = _map_by_point(ctx.working_memory.get("browse_web_pages"))
        wiki_map = _map_by_point(ctx.working_memory.get("wikipedia_search"))
        mw_map = _map_by_point(ctx.working_memory.get("mediawiki_search"))
        gh_map = _map_by_point(ctx.working_memory.get("github_search"))
        se_map = _map_by_point(ctx.working_memory.get("stackexchange_search"))
        q_map = _map_by_point(ctx.working_memory.get("search_questions_by_knowledge"))

        aggregated_items: List[Dict[str, Any]] = []
        for kp in points:
            aggregated_items.append(
                {
                    "knowledge_point": kp,
                    "wikipedia": wiki_map.get(kp) or {},
                    "mediawiki": mw_map.get(kp) or {},
                    "web_search": web_map.get(kp) or {},
                    "web_pages": browse_map.get(kp) or {},
                    "github": gh_map.get(kp) or {},
                    "stackexchange": se_map.get(kp) or {},
                    "questions": q_map.get(kp) or {},
                }
            )

        summary = {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points,
            "items": aggregated_items,
            "counts": {
                "knowledge_points": len(points),
                "web": len([x for x in web_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "pages": len([x for x in browse_map.values() if isinstance(x, dict) and (x.get("pages") or [])]),
                "wiki": len([x for x in wiki_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]),
                "mediawiki": len([x for x in mw_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]),
                "github": len([x for x in gh_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "stackexchange": len([x for x in se_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "questions": len([x for x in q_map.values() if isinstance(x, dict) and (x.get("questions") or x.get("examples") or x.get("exercises"))]),
            },
        }
        ctx.working_memory["aggregated"] = summary
        return summary

    async def _tool_save_markdown_file(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """保存最终自学档案到 Markdown 文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            # Best-effort: try common keys
            markdown = str(ctx.working_memory.get("assemble_study_archive") or ctx.working_memory.get("assemble_markdown") or "").strip()

        rel_dir = str(args.get("dir") or "study_archives").strip() or "study_archives"

        # Resolve repo root: backend/agent/executor.py -> repo root
        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / rel_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize Windows-unfriendly characters in filename.
        safe = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1F]', "_", topic)
        safe = re.sub(r"\\s+", " ", safe).strip()
        safe = safe.strip(". ")
        safe = safe[:80] if len(safe) > 80 else safe
        if not safe:
            safe = "study_archive"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe}_{ts}.md"
        path = out_dir / filename

        try:
            path.write_text(markdown + ("\n" if not markdown.endswith("\n") else ""), encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": str(exc), "dir": str(out_dir), "filename": filename}

        ctx.working_memory["archive_path"] = str(path)
        return {
            "success": True,
            "path": str(path),
            "dir": str(out_dir),
            "filename": filename,
            "bytes": len((markdown or "").encode("utf-8")),
        }

    async def _tool_retrieve_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()

        if not LESSON_PLAN_API_KEY:
            return {
                "topic": topic,
                "subject": subject,
                "difficulty": difficulty,
                "definition": "",
                "key_points": [],
                "prerequisites": [],
                "common_mistakes": [],
                "methods": [],
                "source": "fallback",
                "note": "未配置模型，知识检索返回为空。",
            }

        prompt = f"""请为“{subject}”的知识点“{topic}”生成可用于自学资料的事实性要点。\n\n要求：\n- 输出严格 JSON（不要 Markdown、不要代码块）\n- 字段：definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[])\n- 难度参考：{difficulty}\n"""
        text = await self._call_llm_text(
            messages=[{"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"}, {"role": "user", "content": prompt}],
            model=self.config.summarizer_model,
            temperature=0.2,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "difficulty": difficulty,
            "definition": str(obj.get("definition") or ""),
            "key_points": list(obj.get("key_points") or []),
            "prerequisites": list(obj.get("prerequisites") or []),
            "common_mistakes": list(obj.get("common_mistakes") or []),
            "methods": list(obj.get("methods") or []),
            "source": "llm",
        }

    async def _tool_search_examples(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 3)
        limit = max(1, min(5, limit))

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(12, limit * 4),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        picked = self._pick_questions(questions, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "examples": picked}

    async def _tool_search_exercises(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 10)
        limit = max(5, min(30, limit))

        used_ids: set[str] = set()
        prev = ctx.working_memory.get("search_examples")
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                qid = str(q.get("question_id") or "").strip()
                if qid:
                    used_ids.add(qid)

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(20, limit * 3),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        filtered = [q for q in questions if str(q.get("question_id") or "").strip() not in used_ids]
        picked = self._pick_questions(filtered, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "exercises": picked}

    async def _tool_analyze_topic(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}

        if not LESSON_PLAN_API_KEY:
            return {
                "topic": topic,
                "subject": subject,
                "outline": ["概念与定义", "常用方法", "例题精讲", "分层练习"],
                "confusions": [],
                "source": "fallback",
            }

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "required_output": {
                "outline": "string[]",
                "confusions": "string[]",
                "teaching_order": "string[]",
            },
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的教学设计专家，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "outline": list(obj.get("outline") or []),
            "confusions": list(obj.get("confusions") or []),
            "teaching_order": list(obj.get("teaching_order") or []),
            "source": "llm",
        }

    async def _tool_generate_explanation(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        analysis = ctx.working_memory.get("analyze_topic") if isinstance(ctx.working_memory.get("analyze_topic"), dict) else {}

        if not LESSON_PLAN_API_KEY:
            return (
                f"## 一、知识点讲解：{topic}\n\n"
                "（未配置模型，无法生成详细讲解。你可以先配置 `.env` 中的 `LESSON_PLAN_*` 后重试。）\n"
            )

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "analysis": analysis,
            "instructions": "请生成 Markdown 章节：知识点讲解。包含：定义、关键点、常见误区、方法小结。不要输出练习题。",
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.4,
            max_tokens=1400,
        )
        return text.strip()

    async def _tool_generate_solutions(self, args: Dict[str, Any], ctx: CompressedContext) -> List[Dict[str, Any]]:
        max_examples = int(args.get("max_examples") or 3)
        max_examples = max(1, min(5, max_examples))

        prev = ctx.working_memory.get("search_examples")
        examples: List[Dict[str, Any]] = []
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                if isinstance(q, dict):
                    examples.append(q)
        examples = examples[:max_examples]

        if not examples:
            return []

        if not LESSON_PLAN_API_KEY:
            return [
                {
                    "question_id": q.get("question_id"),
                    "stem": q.get("stem"),
                    "solution_markdown": "（未配置模型，无法生成解答。）",
                }
                for q in examples
            ]

        solutions: List[Dict[str, Any]] = []
        for idx, q in enumerate(examples, start=1):
            stem = str(q.get("stem") or "").strip()
            prompt = f"""请为下面例题写出详细分步解答（Markdown）。\n\n要求：\n- 每一步说明在做什么\n- 如果题干信息不足，请说明需要补充什么\n\n题目：\n{stem}\n"""
            sol = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的数学解题老师，输出必须是Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.config.planner_model,
                temperature=0.3,
                max_tokens=1200,
            )
            solutions.append(
                {
                    "index": idx,
                    "question_id": q.get("question_id"),
                    "source": q.get("source"),
                    "difficulty": q.get("difficulty"),
                    "stem": stem,
                    "solution_markdown": (sol or "").strip(),
                }
            )
        return solutions

    async def _tool_assemble_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()

        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        explanation = ctx.working_memory.get("generate_explanation")
        solutions = ctx.working_memory.get("generate_solutions")
        exercises = ctx.working_memory.get("search_exercises") if isinstance(ctx.working_memory.get("search_exercises"), dict) else {}

        lines: List[str] = []
        lines.append(f"# 自学材料：{topic}")
        if subject:
            lines.append("")
            lines.append(f"> 学科：{subject}")

        # Knowledge block (structured) + explanation block (markdown)
        definition = str(knowledge.get("definition") or "").strip()
        key_points = knowledge.get("key_points") if isinstance(knowledge.get("key_points"), list) else []
        prereq = knowledge.get("prerequisites") if isinstance(knowledge.get("prerequisites"), list) else []
        mistakes = knowledge.get("common_mistakes") if isinstance(knowledge.get("common_mistakes"), list) else []
        methods = knowledge.get("methods") if isinstance(knowledge.get("methods"), list) else []

        lines.append("")
        lines.append("## 一、知识点讲解")
        lines.append("")
        if definition:
            lines.append("### 1) 定义")
            lines.append("")
            lines.append(definition)
            lines.append("")
        if key_points:
            lines.append("### 2) 关键点")
            lines.append("")
            for x in key_points:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if prereq:
            lines.append("### 3) 前置知识")
            lines.append("")
            for x in prereq:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if mistakes:
            lines.append("### 4) 常见误区")
            lines.append("")
            for x in mistakes:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if methods:
            lines.append("### 5) 方法小结")
            lines.append("")
            for x in methods:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        if isinstance(explanation, str) and explanation.strip():
            lines.append("### 6) 讲解稿")
            lines.append("")
            lines.append(explanation.strip())
            lines.append("")

        # Examples + solutions
        lines.append("## 二、例题精讲（含步骤）")
        lines.append("")
        if isinstance(solutions, list) and solutions:
            for item in solutions:
                stem = str(item.get("stem") or "").strip()
                sol_md = str(item.get("solution_markdown") or "").strip()
                idx = item.get("index") or ""
                lines.append(f"### 例题 {idx}".strip())
                lines.append("")
                if stem:
                    lines.append("**题目**：")
                    lines.append("")
                    lines.append(stem)
                    lines.append("")
                if sol_md:
                    lines.append("**解答**：")
                    lines.append("")
                    lines.append(sol_md)
                    lines.append("")
                else:
                    lines.append("（未生成解答）")
                    lines.append("")
        else:
            examples = ctx.working_memory.get("search_examples")
            if isinstance(examples, dict) and examples.get("examples"):
                for i, q in enumerate(examples.get("examples") or [], start=1):
                    if not isinstance(q, dict):
                        continue
                    lines.append(f"### 例题 {i}")
                    lines.append("")
                    lines.append(str(q.get("stem") or "").strip())
                    lines.append("")
            else:
                lines.append("（未检索到例题）")
                lines.append("")

        # Exercises (no solutions)
        lines.append("## 三、练习题（不含答案）")
        lines.append("")
        ex_list = exercises.get("exercises") if isinstance(exercises.get("exercises"), list) else []
        if ex_list:
            for i, q in enumerate(ex_list, start=1):
                if not isinstance(q, dict):
                    continue
                stem = str(q.get("stem") or "").strip()
                if not stem:
                    continue
                lines.append(f"{i}. {stem}")
                lines.append("")
        else:
            lines.append("（未检索到练习题）")
            lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return markdown

    async def _tool_review_content(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        markdown = str(ctx.working_memory.get("markdown") or "")

        # Heuristic checks (source coverage) to encourage deep research iterations.
        # We only fail the review when at least some upstream retrieval worked; otherwise we'd loop
        # endlessly on missing API keys/network constraints.
        heuristic_issues: List[str] = []
        heuristic_suggestions: List[str] = []

        aggregated = ctx.working_memory.get("aggregated") or ctx.working_memory.get("aggregate_knowledge")
        if isinstance(aggregated, dict) and isinstance(aggregated.get("items"), list):
            items = [x for x in (aggregated.get("items") or []) if isinstance(x, dict)]

            def _count_list(obj: Any, key: str) -> int:
                if not isinstance(obj, dict):
                    return 0
                v = obj.get(key)
                return len(v) if isinstance(v, list) else 0

            any_web = any(_count_list(it.get("web_search"), "results") > 0 for it in items)
            any_wiki = any(
                str((it.get("wikipedia") or {}).get("summary") or "").strip()
                or str((it.get("mediawiki") or {}).get("summary") or "").strip()
                for it in items
                if isinstance(it, dict)
            )
            any_stackexchange = any(_count_list(it.get("stackexchange"), "results") > 0 for it in items)

            enforce_sources = any_web or any_wiki or any_stackexchange

            for it in items:
                kp = str(it.get("knowledge_point") or "").strip() or "（未命名知识点）"

                wiki_summary = str((it.get("wikipedia") or {}).get("summary") or "").strip()
                mw_summary = str((it.get("mediawiki") or {}).get("summary") or "").strip()

                web_n = _count_list(it.get("web_search"), "results")
                pages_n = _count_list(it.get("web_pages"), "pages")
                se_n = _count_list(it.get("stackexchange"), "results")
                gh_n = _count_list(it.get("github"), "results")

                sources_ok = bool(wiki_summary or mw_summary) or web_n >= 3 or pages_n >= 1 or se_n >= 1 or gh_n >= 1
                if enforce_sources and not sources_ok:
                    heuristic_issues.append(
                        f"知识点「{kp}」资料来源不足：百科/网搜/网页正文/问答/GitHub 均较少；建议增加搜索轮次或调整 query_hint。"
                    )

                examples_n = _count_list((it.get("questions") or {}), "examples")
                exercises_n = _count_list((it.get("questions") or {}), "exercises")
                if examples_n + exercises_n <= 0:
                    heuristic_suggestions.append(
                        f"知识点「{kp}」题库未返回例题/练习题：可提高 max_pages、放宽筛选或换更具体关键词。"
                    )

        if heuristic_issues:
            return {
                "passed": False,
                "issues": heuristic_issues[:8],
                "suggestions": heuristic_suggestions[:8],
                "source": "heuristic",
            }

        if not LESSON_PLAN_API_KEY:
            return {"passed": True, "issues": [], "suggestions": [], "source": "fallback"}

        prompt = f"""请审查下面这份自学资料 Markdown，找出：\n1) 逻辑跳跃/不清晰处\n2) 可能的错误或表述不严谨\n3) 建议改进点（最多5条）\n\n要求：输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=self.config.reflector_model,
            temperature=0.1,
            max_tokens=900,
        )
        obj = self._extract_json_obj(text)
        return {
            "passed": bool(obj.get("passed")) if "passed" in obj else True,
            "issues": list(obj.get("issues") or []),
            "suggestions": list(obj.get("suggestions") or []),
            "source": "llm",
        }

    async def _tool_revise_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        issues = args.get("issues") or []
        markdown = str(ctx.working_memory.get("markdown") or "")
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_markdown") or "")

        if not LESSON_PLAN_API_KEY or not markdown:
            return markdown

        prompt = {
            "issues": issues,
            "instructions": "请根据 issues 修订 Markdown，保持结构：讲解→例题→练习题（练习题不含答案）。仅输出修订后的Markdown。",
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编辑，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=1600,
        )
        revised = (text or "").strip()
        if revised:
            ctx.working_memory["markdown"] = revised
            return revised
        return markdown
