from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.core.subjects import resolve_subject
from backend.database.repositories.question.papers import get_paper, save_paper
from backend.generation.paper_compose.analysis import analyze_paper as analyze_paper_sync
from backend.generation.paper_compose.auto_planner import plan_exam_structure
from backend.generation.paper_compose.exporters.latex import compile_latex_to_pdf_async, render_paper_latex
from backend.integrations.crawler.manager import get_crawler
from backend.llm.client import is_llm_configured
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes, publish_generated_text

logger = get_logger(__name__)


def _as_int(value: Any, default: int, *, min_v: int = 0, max_v: int = 10_000) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = int(default)
    return max(min_v, min(max_v, n))


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any, default: str = "") -> str:
    raw = str(value if value is not None else "").strip()
    return raw or default


def _extract_tex_from_response(text: str, fallback: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return fallback
    obj: Dict[str, Any] = {}
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except (TypeError, ValueError, json.JSONDecodeError):
                obj = {}
    tex = _text(obj.get("latex_tex") if isinstance(obj, dict) else "")
    if tex:
        return tex
    fenced = re.search(r"```(?:tex|latex)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return raw if "\\documentclass" in raw else fallback


class PaperComposeToolsMixin:
    async def _paper_crawler(self, args: Dict[str, Any], ctx: CompressedContext):
        subject_input = _text(args.get("subject") or ctx.user_profile.preferences.get("subject") or ctx.current_task)
        edu_level = _text(args.get("edu_level"))
        try:
            subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
        except ValueError:
            subject = subject_input
        return await get_crawler(subject=subject, edu_level=edu_level, strict=False), subject, edu_level

    async def _tool_get_available_filters(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """获取组卷题库可用筛选项。"""

        crawler, subject, edu_level = await self._paper_crawler(args, ctx)
        result = await crawler.get_available_filters()
        result["applied_subject"] = subject
        if edu_level:
            result["applied_edu_level"] = edu_level
        ctx.working_memory["paper_available_filters"] = result
        return result

    async def _tool_search_questions(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """按关键词从题库检索候选题。"""

        crawler, subject, edu_level = await self._paper_crawler(args, ctx)
        keyword = _text(args.get("keyword") or args.get("topic") or ctx.current_task)
        result = await crawler.search_by_keyword(
            keyword=keyword,
            subject=subject,
            edu_level=edu_level,
            limit=_as_int(args.get("limit"), 20, min_v=1, max_v=80),
            difficulty=_text(args.get("difficulty")),
            question_type=_text(args.get("question_type") or args.get("type")),
            learn_grade=_text(args.get("learn_grade")),
            learn_grade_id=_as_int(args.get("learn_grade_id"), 0),
            textbook_version=_text(args.get("textbook_version")),
            max_pages=_as_int(args.get("max_pages"), 2, min_v=1, max_v=5),
            year=_as_int(args.get("year"), 0),
            province=_text(args.get("province")),
            province_id=_as_int(args.get("province_id"), -1, min_v=-1),
            paper_type_id=_as_int(args.get("paper_type_id"), 0),
            term=_as_int(args.get("term"), 0),
            order_by=_as_int(args.get("order_by"), 2),
            dedup_by_stem=bool(args.get("dedup_by_stem", True)),
            min_quality_score=_as_int(args.get("min_quality_score"), 0, min_v=0, max_v=100),
            with_quality=True,
            strict_subject=bool(args.get("strict_subject", True)),
            require_difficulty=bool(args.get("require_difficulty", False)),
        )
        ctx.working_memory["search_questions"] = result
        return result

    async def _tool_batch_get_question_details(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """批量获取题目详情。"""

        crawler, _subject, _edu_level = await self._paper_crawler(args, ctx)
        raw_ids = args.get("question_ids") or args.get("ids") or []
        question_ids = [_text(x) for x in _as_list(raw_ids) if _text(x)]
        if not question_ids:
            previous = ctx.working_memory.get("search_questions")
            if isinstance(previous, dict):
                question_ids = [_text(q.get("question_id")) for q in _as_list(previous.get("questions")) if isinstance(q, dict)]
        max_concurrent = _as_int(args.get("max_concurrent"), 5, min_v=1, max_v=20)
        result = await crawler.batch_get_question_details(question_ids[:200], max_concurrent=max_concurrent)
        ctx.working_memory["question_details"] = result
        return result

    async def _tool_compose_paper_blueprint(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """按蓝图从题库组装题目。"""

        crawler, subject, edu_level = await self._paper_crawler(args, ctx)
        blueprint = _as_list(args.get("blueprint"))
        if not blueprint:
            planned = await plan_exam_structure(
                subject=subject,
                topic=_text(args.get("topic") or ctx.current_task),
                total_points=_as_int(args.get("total_points") or args.get("totalPoints"), 150, min_v=1, max_v=300),
                time_limit=_as_int(args.get("time_limit") or args.get("timeLimit"), 120, min_v=1, max_v=300),
            )
            blueprint = _as_list(planned.get("slots") if isinstance(planned, dict) else [])
        result = await crawler.compose_paper_blueprint(
            blueprint=[x for x in blueprint if isinstance(x, dict)],
            subject=subject,
            edu_level=edu_level,
            learn_grade=_text(args.get("learn_grade")),
            learn_grade_id=_as_int(args.get("learn_grade_id"), 0),
            textbook_version=_text(args.get("textbook_version")),
            elective_mode=_text(args.get("elective_mode")),
            elective_keywords=[_text(x) for x in _as_list(args.get("elective_keywords")) if _text(x)] or None,
            exclude_elective=bool(args.get("exclude_elective", False)),
            year=_as_int(args.get("year"), 0),
            province=_text(args.get("province")),
            province_id=_as_int(args.get("province_id"), -1, min_v=-1),
            paper_type_id=_as_int(args.get("paper_type_id"), 0),
            term=_as_int(args.get("term"), 0),
            order_by=_as_int(args.get("order_by"), 2),
            max_pages=_as_int(args.get("max_pages"), 2, min_v=1, max_v=5),
            per_slot_expand=_as_int(args.get("per_slot_expand"), 3, min_v=1, max_v=12),
            min_quality_score=_as_int(args.get("min_quality_score"), 0, min_v=0, max_v=100),
            dedup_by_stem=bool(args.get("dedup_by_stem", True)),
            strict_subject=bool(args.get("strict_subject", True)),
            slot_concurrency=_as_int(args.get("slot_concurrency"), 0, min_v=0, max_v=12),
            slot_delay_s=float(args.get("slot_delay_s") or 0.0),
            slot_retries=_as_int(args.get("slot_retries"), 1, min_v=0, max_v=5),
        )
        ctx.working_memory["paper_blueprint"] = result
        return result

    async def _tool_review_question_match(self, args: Dict[str, Any], _ctx: CompressedContext) -> Dict[str, Any]:
        """启发式检查候选题与目标 slot 的匹配度。"""

        question = args.get("question") if isinstance(args.get("question"), dict) else {}
        slot = args.get("slot") if isinstance(args.get("slot"), dict) else {}
        target_type = _text(slot.get("question_type") or slot.get("type"))
        target_difficulty = _text(slot.get("difficulty"))
        q_type = _text(question.get("type") or question.get("question_type"))
        q_diff = _text(question.get("difficulty"))
        score = 100
        issues: list[str] = []
        if target_type and q_type and target_type != q_type:
            score -= 30
            issues.append("question_type_mismatch")
        if target_difficulty and q_diff and target_difficulty not in q_diff and q_diff not in target_difficulty:
            score -= 20
            issues.append("difficulty_mismatch")
        if not _text(question.get("stem")):
            score -= 40
            issues.append("missing_stem")
        return {"score": max(0, score), "passed": score >= 60, "issues": issues}

    async def _tool_create_paper(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """保存试卷并写入题目快照。"""

        user_id = _text(getattr(ctx.user_profile, "user_id", "") or args.get("user_id"), "anonymous")
        questions = _as_list(args.get("questions"))
        if not questions:
            details = ctx.working_memory.get("question_details")
            if isinstance(details, dict):
                questions = _as_list(details.get("questions"))
        if not questions:
            generated = ctx.working_memory.get("generated_questions_ai")
            if isinstance(generated, dict):
                questions = _as_list(generated.get("questions"))
        paper_name = _text(args.get("paper_name") or args.get("paperName"), "Agentic 生成试卷")
        paper_id = await save_paper(user_id=user_id, paper_name=paper_name, questions=[q for q in questions if isinstance(q, dict)])
        result = {"success": True, "paper_id": int(paper_id), "paper_name": paper_name, "question_count": len(questions)}
        ctx.working_memory["paper_id"] = int(paper_id)
        ctx.working_memory["paper"] = {
            "paper_id": int(paper_id),
            "paper_name": paper_name,
            "subject": _text(args.get("subject") or ctx.user_profile.preferences.get("subject")),
            "questions": [q for q in questions if isinstance(q, dict)],
        }
        return result

    async def _tool_analyze_paper(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """分析试卷题型、难度和知识点分布。"""

        paper = args.get("paper") if isinstance(args.get("paper"), dict) else ctx.working_memory.get("paper")
        if not isinstance(paper, dict):
            paper_id = _as_int(args.get("paper_id") or ctx.working_memory.get("paper_id"), 0)
            if paper_id:
                paper = await get_paper(user_id=_text(ctx.user_profile.user_id), paper_id=paper_id)
        if not isinstance(paper, dict):
            raise ValueError("paper_missing")
        result = analyze_paper_sync(paper)
        ctx.working_memory["paper_analysis"] = result
        return result

    async def _tool_crawl_questions_from_bank(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """从题库按关键词或知识点抓取候选题。"""

        mode = _text(args.get("mode"), "keyword")
        crawler, subject, edu_level = await self._paper_crawler(args, ctx)
        keyword = _text(args.get("keyword") or args.get("topic") or ctx.current_task)
        limit = _as_int(args.get("limit"), 20, min_v=1, max_v=80)
        common = {
            "subject": subject,
            "edu_level": edu_level,
            "limit": limit,
            "difficulty": _text(args.get("difficulty")),
            "question_type": _text(args.get("question_type") or args.get("type")),
            "max_pages": _as_int(args.get("max_pages"), 2, min_v=1, max_v=5),
            "dedup_by_stem": bool(args.get("dedup_by_stem", True)),
            "min_quality_score": _as_int(args.get("min_quality_score"), 10, min_v=0, max_v=100),
            "with_quality": True,
            "strict_subject": bool(args.get("strict_subject", True)),
            "require_difficulty": bool(args.get("require_difficulty", False)),
        }
        if mode == "knowledge":
            result = await crawler.search_by_knowledge(knowledge_point=keyword, **common)
        else:
            result = await crawler.search_by_keyword(keyword=keyword, **common)
        ctx.working_memory["crawl_questions_from_bank"] = result
        return result

    async def _tool_generate_questions_ai(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """调用原创题生成链路生成候选题。"""

        from backend.generation.question_library.generation import generate_questions

        subject = _text(args.get("subject") or ctx.user_profile.preferences.get("subject"))
        topic = _text(args.get("topic") or ctx.current_task)
        source_pack = args.get("source_pack") if isinstance(args.get("source_pack"), dict) else {}
        if not source_pack:
            source_pack = {"subject": subject, "topic": topic, "study_markdown": _text(args.get("study_markdown"))}
        questions = await generate_questions(
            source_pack=source_pack,
            count=_as_int(args.get("count"), 1, min_v=1, max_v=20),
            difficulty=_text(args.get("difficulty"), "中等"),
            question_type=_text(args.get("question_type") or args.get("type"), "解答题"),
            user_id=_text(ctx.user_profile.user_id),
            stream_reasoning=False,
            config=args.get("config") if isinstance(args.get("config"), dict) else None,
        )
        result = {"success": True, "questions": questions, "count": len(questions), "source": "ai"}
        ctx.working_memory["generated_questions_ai"] = result
        return result

    async def _tool_solve_question_independently(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """独立解题并和参考答案比对。"""

        from backend.generation.question_library.judging import solve_draft

        question = args.get("question") if isinstance(args.get("question"), dict) else {}
        stem = _text(args.get("stem") or question.get("stem"))
        answer = _text(args.get("answer") or question.get("answer") or question.get("solution"))
        if not stem:
            raise ValueError("question_stem_missing")
        result = await solve_draft(
            stem,
            {"subject": _text(args.get("subject") or ctx.user_profile.preferences.get("subject")), "proposed_answer": answer},
            stream_reasoning=False,
        )
        ctx.working_memory["solve_question_independently"] = result
        return result

    async def _tool_render_paper_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """把试卷渲染为 LaTeX 并写入 working_memory['latex_tex']。"""

        paper = args.get("paper") if isinstance(args.get("paper"), dict) else ctx.working_memory.get("paper")
        if not isinstance(paper, dict):
            paper_id = _as_int(args.get("paper_id") or ctx.working_memory.get("paper_id"), 0)
            if paper_id:
                paper = await get_paper(user_id=_text(ctx.user_profile.user_id), paper_id=paper_id)
        if not isinstance(paper, dict):
            raise ValueError("paper_missing")
        tex = render_paper_latex(
            paper,
            include_stem=bool(args.get("include_stem", True)),
            include_answer=bool(args.get("include_answer", True)),
            include_analysis=bool(args.get("include_analysis", True)),
        )
        ctx.working_memory["latex_tex"] = tex
        published = await publish_generated_text(
            tex,
            user_id=_text(ctx.user_profile.user_id, "anonymous"),
            ext=".tex",
            file_type="tex",
            mime_type="application/x-tex; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        ctx.working_memory["tex_url"] = published.get("url")
        return {"latex_tex": tex, "tex_url": published.get("url"), "bytes": len(tex.encode("utf-8"))}

    async def _tool_compile_latex_sandbox(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """使用 PAPER_EXPORT_LATEX_BACKEND 编译 LaTeX，并优先走 Docker 沙盒。"""

        tex = _text(args.get("latex_tex") or ctx.working_memory.get("latex_tex"))
        if not tex:
            raise ValueError("latex_missing")
        pdf_bytes, log_text = await compile_latex_to_pdf_async(
            tex=tex,
            timeout_s=float(args.get("timeout_s") or 0) or None,
        )
        ctx.working_memory["latex_compile_log"] = log_text
        if not pdf_bytes:
            raise RuntimeError(f"latex_compile_failed: {log_text[-2000:]}")
        published = await publish_generated_bytes(
            pdf_bytes,
            user_id=_text(ctx.user_profile.user_id, "anonymous"),
            ext=".pdf",
            file_type="pdf",
            mime_type="application/pdf",
            ttl_s=default_generated_media_ttl_s(),
        )
        result = {
            "pdf_url": published.get("url"),
            "filename": published.get("filename"),
            "sha256": published.get("sha256"),
            "bytes": int(published.get("bytes") or 0),
            "log": log_text[-2000:],
        }
        ctx.working_memory["pdf_url"] = result["pdf_url"]
        return result

    async def _tool_repair_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """根据编译日志回修 LaTeX，供 compiler 重试。"""

        tex = _text(args.get("latex_tex") or ctx.working_memory.get("latex_tex"))
        log_text = _text(args.get("compile_log") or ctx.working_memory.get("latex_compile_log"))
        if not tex:
            raise ValueError("latex_missing")
        if not is_llm_configured():
            return {"latex_tex": tex, "changed": False, "reason": "llm_not_configured"}

        prompt = {
            "task": "Repair the LaTeX so xelatex can compile it. Output JSON only with field latex_tex.",
            "latex_tex": tex[-30000:],
            "compile_log": log_text[-6000:],
        }
        repaired_text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "You repair LaTeX documents. Output strict JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.summarizer_model,
            temperature=0.1,
            max_tokens=12000,
            response_format={"type": "json_object"},
            raise_on_fail=True,
        )
        repaired = _extract_tex_from_response(repaired_text, tex).strip()
        if repaired:
            ctx.working_memory["latex_tex"] = repaired
        return {"latex_tex": repaired or tex, "changed": bool(repaired and repaired != tex)}
