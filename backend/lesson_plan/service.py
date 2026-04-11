from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.llm.client import is_llm_configured
from backend.core.settings import LESSON_PLAN_SUBAGENT_CONCURRENCY
from backend.lesson_plan.common import agent_event
from backend.lesson_plan.export import (
    compile_latex_to_pdf,
    convert_markdown_to_latex,
    publish_generated_text,
    refine_latex,
)
from backend.lesson_plan.planning import research_knowledge_point, review_knowledge_points, split_knowledge_points
from backend.lesson_plan.writing import generate_lesson_plan_json, lesson_plan_to_markdown


async def generate_lesson_plan_stream(
    subject: str,
    grade: str,
    topic: str,
    *,
    user_id: str,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    teaching_style: Optional[str] = None,
    student_level: Optional[str] = None,
    additional_requirements: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Generate a lesson plan and export Markdown/PDF (streaming SSE events)."""

    if not is_llm_configured():
        yield agent_event("error", {"message": "llm_not_configured"})
        return

    subject = (subject or "").strip()
    grade = (grade or "").strip()
    topic = (topic or "").strip()
    try:
        duration_minutes = int(duration_minutes or 45)
    except Exception:
        duration_minutes = 45
    duration_minutes = max(20, min(duration_minutes, 180))

    try:
        yield agent_event("thinking", {"content": f"分析教学需求：{subject} {grade}《{topic}》…"})

        split_step_id = f"split_knowledge_points-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": split_step_id,
                "name": "split_knowledge_points",
                "title": "拆分知识点",
                "arguments": {"topic": topic, "subject": subject, "min_points": 3, "max_points": 10},
            },
        )
        t0 = time.monotonic()
        knowledge_points = await split_knowledge_points(topic, subject, min_points=3, max_points=10)
        yield agent_event(
            "tool_result",
            {
                "step_id": split_step_id,
                "name": "split_knowledge_points",
                "title": "拆分知识点",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {"knowledge_points": knowledge_points, "count": len(knowledge_points)},
            },
        )

        review_step_id = f"review_knowledge_points-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": review_step_id,
                "name": "review_knowledge_points",
                "title": "审核知识点列表",
                "arguments": {"topic": topic, "subject": subject, "knowledge_points": knowledge_points},
            },
        )
        t0 = time.monotonic()
        knowledge_points = await review_knowledge_points(topic, subject, knowledge_points, min_points=3, max_points=10)
        yield agent_event(
            "tool_result",
            {
                "step_id": review_step_id,
                "name": "review_knowledge_points",
                "title": "审核知识点列表",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {
                    "knowledge_points": knowledge_points,
                    "count": len(knowledge_points),
                    "source": "review_llm",
                },
            },
        )

        research_results: List[Dict[str, Any]] = [{} for _ in range(len(knowledge_points))]

        try:
            conc_raw = int(LESSON_PLAN_SUBAGENT_CONCURRENCY or 0)
        except Exception:
            conc_raw = 0
        conc = max(1, min(conc_raw if conc_raw > 0 else 3, 20))
        sem = asyncio.Semaphore(conc)

        async def _run_one(*, i: int, kp: str, step_id: str) -> Dict[str, Any]:
            async with sem:
                t1 = time.monotonic()
                res = await research_knowledge_point(kp, subject, topic)
                return {
                    "index": i,
                    "knowledge_point": kp,
                    "step_id": step_id,
                    "elapsed_ms": int((time.monotonic() - t1) * 1000),
                    "result": res,
                }

        tasks: List[asyncio.Task] = []
        for i, kp in enumerate(knowledge_points):
            yield agent_event(
                "subagent_start",
                {
                    "knowledge_point": kp,
                    "index": i,
                    "total": len(knowledge_points),
                    "content": f"SubAgent 启动：研究知识点「{kp}」",
                },
            )
            step_id = f"research_knowledge_point-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": step_id,
                    "name": "research_knowledge_point",
                    "title": f"研究知识点：{kp}",
                    "arguments": {"knowledge_point": kp, "subject": subject, "topic": topic},
                },
            )
            tasks.append(asyncio.create_task(_run_one(i=i, kp=kp, step_id=step_id)))

        try:
            for fut in asyncio.as_completed(tasks):
                r = await fut
                i = int(r.get("index") or 0)
                kp = str(r.get("knowledge_point") or "")
                step_id = str(r.get("step_id") or "")
                elapsed_ms = int(r.get("elapsed_ms") or 0)
                res = r.get("result") if isinstance(r.get("result"), dict) else {}
                if 0 <= i < len(research_results):
                    research_results[i] = res

                yield agent_event(
                    "tool_result",
                    {
                        "step_id": step_id,
                        "name": "research_knowledge_point",
                        "title": f"研究知识点：{kp}",
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                        "output": {"knowledge_point": kp, "has_research": bool(res.get("research"))},
                    },
                )
                yield agent_event(
                    "subagent_end",
                    {
                        "knowledge_point": kp,
                        "index": i,
                        "total": len(knowledge_points),
                        "content": f"SubAgent 完成：「{kp}」资料收集完毕",
                    },
                )
        except Exception:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        yield agent_event("thinking", {"content": "根据收集的资料，撰写教案正文（原创撰写）…"})

        research_context: List[Dict[str, Any]] = []
        for r in research_results:
            kp = str(r.get("knowledge_point") or "").strip()
            blob = r.get("research") if isinstance(r.get("research"), dict) else {}
            if kp and blob:
                research_context.append({"knowledge_point": kp, **blob})

        gen_step_id = f"generate_lesson_plan-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": gen_step_id,
                "name": "generate_lesson_plan",
                "title": "生成教案",
                "arguments": {
                    "subject": subject,
                    "grade": grade,
                    "topic": topic,
                    "duration_minutes": duration_minutes,
                    "knowledge_points": knowledge_points,
                },
            },
        )
        t0 = time.monotonic()
        plan = await generate_lesson_plan_json(
            subject=subject,
            grade=grade,
            topic=topic,
            duration_minutes=duration_minutes,
            objectives=objectives,
            teaching_style=teaching_style,
            student_level=student_level,
            additional_requirements=additional_requirements,
            knowledge_points=knowledge_points,
            research_context=research_context,
        )
        yield agent_event(
            "tool_result",
            {
                "step_id": gen_step_id,
                "name": "generate_lesson_plan",
                "title": "生成教案",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {"title": str(plan.get("title") or ""), "sections": len(plan.get("sections") or [])},
            },
        )

        assemble_id = f"assemble_study_archive-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": assemble_id,
                "name": "assemble_study_archive",
                "title": "组装 Markdown",
                "arguments": {"topic": topic, "subject": subject},
            },
        )
        t0 = time.monotonic()
        md = lesson_plan_to_markdown(
            plan,
            subject=subject,
            grade=grade,
            topic=topic,
            duration_minutes=duration_minutes,
            knowledge_points=knowledge_points,
        )
        yield agent_event(
            "tool_result",
            {
                "step_id": assemble_id,
                "name": "assemble_study_archive",
                "title": "组装 Markdown",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {"markdown_chars": len(md)},
            },
        )

        title = str(plan.get("title") or topic or "教案").strip() or "教案"

        export_md_id = f"export_study_markdown-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": export_md_id,
                "name": "export_study_markdown",
                "title": "导出 Markdown",
                "arguments": {"topic": topic, "subject": subject},
            },
        )
        t0 = time.monotonic()
        md_pub = await publish_generated_text(
            md, user_id=user_id, ext=".md", file_type="md", mime_type="text/markdown; charset=utf-8"
        )
        yield agent_event(
            "tool_result",
            {
                "step_id": export_md_id,
                "name": "export_study_markdown",
                "title": "导出 Markdown",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {"md_url": md_pub["url"], "filename": md_pub["filename"], "bytes": md_pub["bytes"]},
            },
        )

        convert_id = f"convert_markdown_to_latex-{uuid.uuid4().hex[:8]}"
        yield agent_event(
            "tool_call",
            {
                "step_id": convert_id,
                "name": "convert_markdown_to_latex",
                "title": "Markdown → LaTeX",
                "arguments": {"topic": topic, "subject": subject},
            },
        )
        t0 = time.monotonic()
        tex = await convert_markdown_to_latex(markdown=md, title=title, subject=subject)
        tex_pub = await publish_generated_text(
            tex, user_id=user_id, ext=".tex", file_type="tex", mime_type="application/x-tex; charset=utf-8"
        )
        yield agent_event(
            "tool_result",
            {
                "step_id": convert_id,
                "name": "convert_markdown_to_latex",
                "title": "Markdown → LaTeX",
                "success": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "output": {"tex_url": tex_pub["url"], "filename": tex_pub["filename"], "bytes": tex_pub["bytes"]},
            },
        )

        tex_current = tex
        pdf_pub: Dict[str, Any] = {}
        last_compile_err = ""
        for attempt in range(3):
            refine_id = f"refine_latex-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": refine_id,
                    "name": "refine_latex",
                    "title": f"修订 LaTeX（第{attempt + 1}轮）",
                    "arguments": {"topic": topic, "subject": subject},
                },
            )
            t0 = time.monotonic()
            tex_current = await refine_latex(
                latex=tex_current, topic=topic, subject=subject, compile_error=last_compile_err
            )
            tex_pub2 = await publish_generated_text(
                tex_current,
                user_id=user_id,
                ext=".tex",
                file_type="tex",
                mime_type="application/x-tex; charset=utf-8",
            )
            yield agent_event(
                "tool_result",
                {
                    "step_id": refine_id,
                    "name": "refine_latex",
                    "title": f"修订 LaTeX（第{attempt + 1}轮）",
                    "success": True,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    "output": {
                        "tex_url": tex_pub2["url"],
                        "filename": tex_pub2["filename"],
                        "bytes": tex_pub2["bytes"],
                    },
                },
            )

            compile_id = f"compile_latex_to_pdf-{uuid.uuid4().hex[:8]}"
            yield agent_event(
                "tool_call",
                {
                    "step_id": compile_id,
                    "name": "compile_latex_to_pdf",
                    "title": f"编译 PDF（第{attempt + 1}轮）",
                    "arguments": {"topic": topic},
                },
            )
            t0 = time.monotonic()
            try:
                pdf_pub = await compile_latex_to_pdf(latex=tex_current, user_id=user_id)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": compile_id,
                        "name": "compile_latex_to_pdf",
                        "title": f"编译 PDF（第{attempt + 1}轮）",
                        "success": True,
                        "elapsed_ms": int((time.monotonic() - t0) * 1000),
                        "output": {
                            "pdf_url": pdf_pub["url"],
                            "filename": pdf_pub["filename"],
                            "bytes": pdf_pub["bytes"],
                        },
                    },
                )
                break
            except Exception as exc:
                last_compile_err = str(exc)
                yield agent_event(
                    "tool_result",
                    {
                        "step_id": compile_id,
                        "name": "compile_latex_to_pdf",
                        "title": f"编译 PDF（第{attempt + 1}轮）",
                        "success": False,
                        "elapsed_ms": int((time.monotonic() - t0) * 1000),
                        "error": last_compile_err,
                    },
                )
                if attempt >= 2:
                    raise

        if not pdf_pub:
            raise RuntimeError(f"pdf_missing: {last_compile_err or 'unknown'}")

        yield agent_event(
            "done",
            {
                "material": {
                    "topic": topic,
                    "title": title,
                    "subject": subject,
                    "grade": grade,
                    "duration_minutes": duration_minutes,
                    "md_url": md_pub["url"],
                    "md_filename": md_pub["filename"],
                    "pdf_url": pdf_pub["url"],
                    "pdf_filename": pdf_pub["filename"],
                }
            },
        )
    except Exception as exc:
        yield agent_event("error", {"message": str(exc)})
