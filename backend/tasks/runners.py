from __future__ import annotations

import asyncio
from typing import Any, Dict

from backend.database.repositories.content.study_archives import get_study_archive as db_get_study_archive
from backend.database.repositories.question.papers import get_paper as db_get_paper
from backend.deepthink.service import deepthink_service
from backend.lesson_plan.service import generate_lesson_plan_stream
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text
from backend.paper_compose.export import export_paper as export_paper_doc
from backend.paper_compose.full_paper_workflow import generate_full_paper_events
from backend.paper_compose.workflow import compose_paper_events
from backend.shared.tasks import RuntimeTask, task_runtime


async def run_paper_compose_task(task: RuntimeTask, *, user_id: str) -> None:
    """Run the paper-compose workflow and emit events into the shared task runtime."""

    try:
        async for evt in compose_paper_events(task.request, user_id=user_id):
            if task.status != "running":
                break

            await task_runtime.append_event(task, evt)

            kind = str(evt.get("type") or "")
            if kind == "result":
                result = evt.get("result") if isinstance(evt.get("result"), dict) else {"result": evt.get("result")}
                await task_runtime.complete_task(task, result=result)
                return
            if kind == "error":
                msg = str(evt.get("error") or "compose_failed").strip() or "compose_failed"
                await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
                return
    except asyncio.CancelledError:
        # Lifecycle methods will persist terminal state; avoid double-writing.
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:  # pragma: no cover
        await task_runtime.fail_task(task, str(exc), error={"message": str(exc)})
    finally:
        if task.status == "running":
            await task_runtime.fail_task(task, "Task ended unexpectedly", error={"message": "Task ended unexpectedly"})


async def run_generate_full_paper_task(task: RuntimeTask, *, user_id: str) -> None:
    """Run one-click full-paper generation under the shared task runtime."""

    req = task.request if isinstance(task.request, dict) else {}
    stream_reasoning = bool(req.get("stream_reasoning")) if "stream_reasoning" in req else bool(req.get("streamReasoning"))

    try:
        async for evt in generate_full_paper_events(
            req,
            user_id=user_id,
            stream_reasoning=stream_reasoning,
            on_reasoning_event=None,
        ):
            if task.status != "running":
                break

            await task_runtime.append_event(task, evt)

            kind = str(evt.get("type") or "")
            if kind == "result":
                result = evt.get("result") if isinstance(evt.get("result"), dict) else {"result": evt.get("result")}
                await task_runtime.complete_task(task, result=result)
                return
            if kind == "error":
                msg = str(evt.get("error") or "generate_full_failed").strip() or "generate_full_failed"
                err_data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
                await task_runtime.fail_task(task, msg, error={"message": msg, **(err_data or {})}, emit_event=False)
                return
    except asyncio.CancelledError:
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:  # pragma: no cover
        await task_runtime.fail_task(task, str(exc), error={"message": str(exc)})
    finally:
        if task.status == "running":
            await task_runtime.fail_task(task, "Task ended unexpectedly", error={"message": "Task ended unexpectedly"})


async def run_export_paper_task(task: RuntimeTask, *, user_id: str) -> None:
    """Run paper export under the shared task runtime."""

    uid = str(user_id or "").strip()
    if not uid:
        return

    request = task.request if isinstance(task.request, dict) else {}
    try:
        paper_id = int(request.get("paper_id") or request.get("paperId") or 0)
    except Exception:
        paper_id = 0
    fmt = str(request.get("format") or request.get("fmt") or "markdown").strip().lower()
    include_stem = bool(request.get("include_stem") or request.get("includeStem"))
    include_answer = bool(request.get("include_answer") or request.get("includeAnswer"))
    include_analysis = bool(request.get("include_analysis") or request.get("includeAnalysis"))

    paper = None
    if paper_id > 0:
        try:
            paper = await db_get_paper(user_id=user_id, paper_id=paper_id)
        except Exception:
            paper = None

    if not paper:
        await task_runtime.append_event(
            task,
            {"type": "error", "error": {"code": "paper_not_found", "message": "paper_not_found", "paper_id": paper_id}},
        )
        await task_runtime.fail_task(task, "paper_not_found", error={"message": "paper_not_found"}, emit_event=False)
        return

    await task_runtime.append_event(task, {"type": "progress", "progress": 10.0})

    try:
        out = await export_paper_doc(
            paper,
            user_id=user_id,
            fmt=fmt,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
    except asyncio.CancelledError:
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except ValueError as exc:
        msg = str(exc)
        await task_runtime.append_event(
            task,
            {"type": "error", "error": {"code": "export_invalid_request", "message": msg}},
        )
        await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
        return
    except Exception as exc:  # pragma: no cover
        msg = str(exc)
        await task_runtime.append_event(task, {"type": "error", "error": {"code": "export_failed", "message": msg}})
        await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
        return

    await task_runtime.append_event(task, {"type": "progress", "progress": 95.0})

    if isinstance(out, dict) and out.get("success") is False:
        err_code = str(out.get("error") or "export_failed").strip() or "export_failed"
        await task_runtime.append_event(
            task,
            {"type": "error", "error": {"code": err_code, "message": err_code, "detail": out}},
        )
        await task_runtime.fail_task(task, err_code, error={"message": err_code, "detail": out}, emit_event=False)
        return

    result = dict(out) if isinstance(out, dict) else {"result": out}
    result["paper_id"] = paper_id
    await task_runtime.complete_task(task, result=result)


async def run_export_study_archive_task(task: RuntimeTask, *, user_id: str) -> None:
    """Run study-archive export under the shared task runtime."""

    uid = str(user_id or "").strip()
    if not uid:
        return

    request = task.request if isinstance(task.request, dict) else {}
    try:
        archive_id = int(request.get("archive_id") or request.get("archiveId") or 0)
    except Exception:
        archive_id = 0
    fmt = str(request.get("format") or request.get("fmt") or "markdown").strip().lower()
    if fmt not in {"md", "markdown"}:
        await task_runtime.append_event(
            task,
            {"type": "error", "error": {"code": "unsupported_format", "message": "unsupported_format"}},
        )
        await task_runtime.fail_task(task, "unsupported_format", error={"message": "unsupported_format"}, emit_event=False)
        return

    archive = None
    if archive_id > 0:
        try:
            archive = await db_get_study_archive(user_id=user_id, archive_id=archive_id)
        except Exception:
            archive = None
    if not archive:
        await task_runtime.fail_task(
            task,
            "study_archive_not_found",
            error={"message": "study_archive_not_found"},
        )
        return

    markdown = str(archive.get("markdown") or "").strip()
    if not markdown:
        markdown = f"# {str(archive.get('topic') or '自学资料').strip()}\n\n（无内容）\n"

    await task_runtime.append_event(task, {"type": "progress", "progress": 30.0})

    try:
        out = await publish_generated_text(
            markdown,
            user_id=user_id,
            ext=".md",
            file_type="md",
            mime_type="text/markdown; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
    except asyncio.CancelledError:
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:  # pragma: no cover
        msg = str(exc)
        await task_runtime.append_event(task, {"type": "error", "error": {"code": "export_failed", "message": msg}})
        await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
        return

    result = {"format": "markdown", "archive_id": archive_id, **(out if isinstance(out, dict) else {"result": out})}
    await task_runtime.complete_task(task, result=result)


async def run_deepthink_task(task: RuntimeTask, *, user_id: str) -> None:
    uid = str(user_id or "").strip()
    if not uid:
        return

    req = task.request if isinstance(task.request, dict) else {}
    question = str((req or {}).get("question") or "").strip()
    subject = str((req or {}).get("subject") or "高中数学").strip() or "高中数学"
    image_url = (req or {}).get("image_url") or (req or {}).get("imageUrl")

    try:
        async for event in deepthink_service.solve(question=question, subject=subject, image_url=image_url):
            if task.status != "running":
                return

            payload = dict(event or {}) if isinstance(event, dict) else {"event": event}
            kind = str(payload.get("type") or "event").strip() or "event"
            await task_runtime.append_event(task, payload)

            if kind == "done":
                await task_runtime.complete_task(task, result=payload if isinstance(payload, dict) else {"result": payload})
                return
            if kind == "error":
                msg = str(payload.get("message") or payload.get("error") or "deepthink_failed").strip() or "deepthink_failed"
                await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
                return
    except asyncio.CancelledError:
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:
        msg = str(exc)
        await task_runtime.fail_task(task, msg, error={"message": msg})
    finally:
        if task.status == "running":
            await task_runtime.fail_task(task, "Task ended unexpectedly", error={"message": "Task ended unexpectedly"})


async def run_lesson_plan_task(task: RuntimeTask, *, user_id: str) -> None:
    uid = str(user_id or "").strip()
    if not uid:
        return

    request = task.request if isinstance(task.request, dict) else {}

    try:
        async for event in generate_lesson_plan_stream(
            subject=str((request or {}).get("subject") or "").strip(),
            grade=str((request or {}).get("grade") or "").strip(),
            topic=str((request or {}).get("topic") or "").strip(),
            user_id=uid,
            duration_minutes=(request or {}).get("duration_minutes"),
            objectives=(request or {}).get("objectives"),
            teaching_style=(request or {}).get("teaching_style"),
            student_level=(request or {}).get("student_level"),
            additional_requirements=(request or {}).get("additional_requirements"),
        ):
            if task.status != "running":
                return

            await task_runtime.append_event(task, dict(event or {}))

            kind = str((event or {}).get("event") or "").strip() or "event"
            data = (event or {}).get("data") if isinstance((event or {}).get("data"), dict) else {}

            if kind == "done":
                material = data.get("material") if isinstance(data, dict) else {}
                await task_runtime.complete_task(
                    task,
                    result=material if isinstance(material, dict) else {"material": material},
                )
                return
            if kind == "error":
                msg = str((data or {}).get("message") or "lesson_plan_failed").strip() or "lesson_plan_failed"
                await task_runtime.fail_task(task, msg, error={"message": msg}, emit_event=False)
                return
    except asyncio.CancelledError:
        if task.status != "running":
            async with task.cond:
                task.cond.notify_all()
            raise
        await task_runtime.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:
        msg = str(exc)
        await task_runtime.fail_task(task, msg, error={"message": msg})
    finally:
        if task.status == "running":
            await task_runtime.fail_task(task, "Task ended unexpectedly", error={"message": "Task ended unexpectedly"})
