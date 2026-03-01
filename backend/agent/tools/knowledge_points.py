from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.llm_client import is_llm_configured


class KnowledgePointsToolsMixin:
    async def _tool_split_knowledge_points(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将主题拆分为多个可检索的子知识点。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
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
        if is_llm_configured():
            # Use a faster model for small JSON tasks by default; allow override via env.
            model = str(os.getenv("STUDY_MATERIALS_KP_SPLIT_MODEL") or "").strip()
            if not model:
                model = str(getattr(self.config, "summarizer_model", "") or "").strip() or str(
                    getattr(self.config, "planner_model", "") or ""
                ).strip()

            timeout_raw = (
                os.getenv("STUDY_MATERIALS_KP_SPLIT_TIMEOUT_S")
                or os.getenv("STUDY_MATERIALS_PREPLAN_TIMEOUT_S")
                or ""
            ).strip()
            try:
                timeout_s = float(timeout_raw) if timeout_raw else 25.0
            except Exception:
                timeout_s = 25.0
            timeout_s = max(5.0, min(timeout_s, 180.0))

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
            # Even in strict mode, do not block the whole pipeline if the planner model is slow/hangs.
            # Fall back to Wikipedia/headings/templates if the call times out or fails.
            try:
                text = await asyncio.wait_for(
                    self._call_llm_text(
                        messages=[
                            {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                        ],
                        model=model,
                        temperature=0.2,
                        max_tokens=2400,
                        response_format={"type": "json_object"},
                        reasoning={"effort": "minimal", "exclude": True},
                        raise_on_fail=False,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                text = ""
            except Exception:
                text = ""
            obj = self._extract_json_obj(text)
            points = _clean_points(list(obj.get("knowledge_points") or []))
            if len(points) >= min_points:
                return {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_points": points,
                    "source": "llm",
                    "model": model,
                }
        # If not configured (or failed), fall back to heuristic split.

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
            "note": "LLM 拆分不可用/超时/不足，使用 Wikipedia 结构 + 规则模板增强拆分。",
        }

    async def _tool_review_knowledge_points(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """审核并微调知识点列表（去重/补全/粒度调整）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)

        min_points = int(args.get("min_points") or 2)
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

        provided = args.get("knowledge_points")
        points: List[str] = []
        if isinstance(provided, list):
            points = _clean_points(list(provided))

        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                points = _clean_points(list(split_res.get("knowledge_points") or []))

        original = list(points)

        source = "heuristic"
        note = ""

        if is_llm_configured() and points:
            # Allow override, but default to a faster model for this small JSON-only task.
            model = str(os.getenv("STUDY_MATERIALS_KP_REVIEW_MODEL") or "").strip()
            if not model:
                model = str(getattr(self.config, "summarizer_model", "") or "").strip() or str(
                    getattr(self.config, "planner_model", "") or ""
                ).strip()

            timeout_raw = (
                os.getenv("STUDY_MATERIALS_KP_REVIEW_TIMEOUT_S")
                or os.getenv("STUDY_MATERIALS_PREPLAN_TIMEOUT_S")
                or ""
            ).strip()
            try:
                timeout_s = float(timeout_raw) if timeout_raw else 30.0
            except Exception:
                timeout_s = 30.0
            timeout_s = max(5.0, min(timeout_s, 240.0))

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_points": points,
                "requirements": [
                    "请审核并微调上述知识点列表，使其更适合『逐点检索 + 逐点生成自学讲解』。",
                    f"数量要求：{min_points}~{max_points} 个；尽量不超过 {max_points} 个。",
                    "去重：合并重复/同义项；避免过泛（如“概念”“性质”单独出现）。",
                    "补全：如明显缺失关键子主题，可补充 1~3 个，但不要发散到无关内容。",
                    "粒度：短语级关键词，便于搜索与组织讲解；尽量保持原有顺序逻辑。",
                    '只输出严格 JSON：{"knowledge_points": [...], "note": "..."}（不要 Markdown，不要多余文字）。',
                ],
            }
            last_err = ""
            for attempt in range(3):
                try:
                    text = await asyncio.wait_for(
                        self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的教研员，输出必须是JSON。"},
                                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                            ],
                            model=model,
                            temperature=0.2,
                            max_tokens=2400,
                            response_format={"type": "json_object"},
                            reasoning={"effort": "minimal", "exclude": True},
                            raise_on_fail=False,
                        ),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    last_err = "timeout"
                    break
                except Exception as exc:
                    last_err = str(exc) or "unknown"
                    break
                obj = self._extract_json_obj(text)
                revised = obj.get("knowledge_points")
                if isinstance(revised, list):
                    cleaned = _clean_points(list(revised))
                    if len(cleaned) >= min_points:
                        points = cleaned[:max_points]
                        source = "llm"
                        note = str(obj.get("note") or "").strip()
                        break
                    last_err = f"too_few_points got={len(cleaned)} min={min_points}"
                else:
                    last_err = "invalid_json"
                # Retry once or twice if the model returned invalid JSON/too few points.
                if attempt < 2:
                    continue
                break

            if source != "llm":
                note = (note + "；" if note else "") + f"LLM 审核不可用/超时（{last_err or 'unknown'}），已回退为规则清洗。"

        if topic and len(points) < min_points:
            pads = [
                topic,
                f"{topic} 基本概念",
                f"{topic} 常见题型",
                f"{topic} 典型例题",
                f"{topic} 易错点",
            ]
            points = _clean_points(points + pads)

        points = points[:max_points] if points else ([topic] if topic else [])

        out = {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points,
            "source": f"review_{source}",
        }
        if note:
            out["note"] = note

        removed = [x for x in original if x not in points]
        added = [x for x in points if x not in original]
        if removed or added:
            out["changes"] = {"removed": removed[:10], "added": added[:10]}

        # Make the reviewed list the canonical list for downstream foreach execution.
        try:
            ctx.working_memory["split_knowledge_points"] = {
                "topic": topic,
                "subject": subject,
                "knowledge_points": points,
                "source": f"review_{source}",
                "note": note,
            }
        except Exception:
            pass

        return out
