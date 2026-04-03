from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.llm.client import is_llm_configured


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


def _heuristic_type(kp: str) -> str:
    s = (kp or "").strip()
    if not s:
        return "concept"
    s_lower = s.lower()

    # Prefer explicit/rare categories first.
    if any(x in s for x in ["实验", "探究", "测量", "装置", "仪器", "观测", "现象", "操作"]):
        return "experiment"
    if any(x in s for x in ["历史", "发展", "人物", "年代", "起源", "背景", "里程碑"]):
        return "history"

    if any(
        x in s for x in ["定理", "命题", "引理", "推论", "结论", "定律", "法则", "公式", "恒等式", "不等式", "方程"]
    ):
        return "theorem"

    # "algorithm" here means "procedure/method" (not only CS algorithms).
    if any(
        x in s
        for x in [
            "算法",
            "排序",
            "搜索",
            "动态规划",
            "贪心",
            "回溯",
            "递归",
            "分治",
            "二分",
            "双指针",
            "滑动窗口",
            "解法",
            "方法",
            "技巧",
            "步骤",
            "流程",
            "推导",
            "证明思路",
            "分析",
            "分解",
        ]
    ) or any(x in s_lower for x in ["dp", "bfs", "dfs", "dijkstra"]):
        return "algorithm"

    if any(x in s for x in ["定义", "是什么", "含义", "概念", "记号", "符号", "术语"]):
        return "definition"
    return "concept"


class KnowledgeTypeDetectionToolsMixin:
    async def _tool_detect_knowledge_type(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Detect knowledge point type (definition/theorem/algorithm/concept/history/experiment).

        Writes:
        - ctx.working_memory["knowledge_types"][knowledge_point] = {knowledge_type, ...}
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)  # type: ignore[attr-defined]
        points = _extract_points(args, ctx)

        source_briefs = ctx.working_memory.get("source_briefs")
        source_briefs = dict(source_briefs) if isinstance(source_briefs, dict) else {}

        model = str(
            os.getenv("STUDY_MATERIALS_TYPE_MODEL")
            or getattr(getattr(self, "config", None), "summarizer_model", "")
            or getattr(getattr(self, "config", None), "planner_model", "")
        ).strip()
        if not model:
            model = "gpt-4o-mini"

        async def _detect_one(kp: str) -> Dict[str, Any]:
            brief = source_briefs.get(kp) if isinstance(source_briefs.get(kp), dict) else {}

            if not is_llm_configured():
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                kt = _heuristic_type(kp)
                out = {
                    "knowledge_point": kp,
                    "knowledge_type": kt,
                    "confidence": 0.55,
                    "focus": [],
                    "recommended_sections": [],
                    "source": "heuristic",
                }
                ctx.working_memory.setdefault("knowledge_types", {})[kp] = out
                return out

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_point": kp,
                "source_brief": brief,
                "requirements": [
                    "请判断该知识点最贴近的类型：definition/theorem/algorithm/concept/history/experiment。",
                    "输出写作重点 focus（3~8条短句）以及推荐的结构 recommended_sections（6~12个小节标题短语）。",
                    "只输出严格 JSON：knowledge_type, confidence(0~1), focus(string[]), recommended_sections(string[])。",
                ],
            }

            raw = await self._call_llm_text(  # type: ignore[attr-defined]
                messages=[
                    {"role": "system", "content": "你是知识类型分类助手，只输出 JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.1,
                max_tokens=900,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(raw)  # type: ignore[attr-defined]
            kt = str(obj.get("knowledge_type") or "").strip().lower()
            if kt not in {"definition", "theorem", "algorithm", "concept", "history", "experiment"}:
                kt = _heuristic_type(kp)
            try:
                conf = float(obj.get("confidence") or 0.0)
            except Exception:
                conf = 0.0
            focus = obj.get("focus")
            focus_list = [str(x).strip() for x in focus if str(x).strip()] if isinstance(focus, list) else []
            rec = obj.get("recommended_sections")
            rec_list = [str(x).strip() for x in rec if str(x).strip()] if isinstance(rec, list) else []

            out = {
                "knowledge_point": kp,
                "knowledge_type": kt,
                "confidence": max(0.0, min(conf, 1.0)) if conf else 0.7,
                "focus": focus_list[:10],
                "recommended_sections": rec_list[:16],
                "source": "llm",
            }
            ctx.working_memory.setdefault("knowledge_types", {})[kp] = out
            return out

        items = [await _detect_one(kp) for kp in points]
        return {"topic": topic, "subject": subject, "items": items}
