from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.database.repositories.content.study_archives import (
    get_latest_study_archive,
    get_latest_study_archive_for_subject,
)
from backend.database.repositories.question.question_cache import get_question_cache, upsert_question_cache
from backend.database.repositories.question.question_library import (
    list_question_library_items,
    list_thinking_method_stats,
    upsert_question_library_items,
)
from backend.generation.agentic.task_specs import (
    agentic_task_meta,
    build_agent_run_spec_for_task,
    build_agentic_starter_event,
)
from backend.generation.agentic.codex_runtime import (
    is_codex_runtime_agent_runtime,
    legacy_agent_fallback_enabled,
    run_codex_runtime_task,
)
from backend.generation.question_library.curriculum_context import (
    build_curriculum_context,
    enrich_source_pack_with_curriculum,
)
from backend.generation.question_library.generation import (
    analyze_reference_questions,
    build_source_pack,
    collect_reference_questions,
    enrich_source_pack_with_reference,
    generate_questions,
)
from backend.generation.question_library.media_import import (
    MediaFileRef,
    MediaImportError,
    build_media_question_id,
    extract_questions_from_media_pages,
    load_all_media_pages,
    publish_media_pages_for_preview,
    safe_media_import_task_id,
)
from backend.generation.question_library.preview_store import (
    find_preview_by_session_id,
    load_session,
    new_preview_id,
    new_session_id,
    save_preview,
    save_session,
)
from backend.generation.question_library.runner_support import (
    RunnerError,
    _append_reasoning_status,
    _clamp_float,
    _clamp_int,
    _emit_event,
    _ensure_session,
    _materialize_drafts,
    _merge_reasoning_block,
    infer_question_type_from_topic,
    normalize_topic_key,
)
from backend.generation.question_library.scoring import (
    apply_score_and_hide,
    extract_thinking_depth,
    merge_method_context,
    score_question_batch_with_thinking_depth,
)
from backend.generation.question_library.session_utils import (
    merge_drafts,
    normalize_draft_questions,
)
from backend.generation.question_library.stages import build_stage_progress_payload, get_question_generation_stage
from backend.integrations.crawler.manager import get_crawler
from backend.llm.client import is_llm_configured
from backend.shared.tasks import RuntimeTask, task_runtime

logger = get_logger(__name__)



async def create_crawl_task(
    *,
    user_id: str,
    request: Dict[str, Any],
    parent_task_id: Optional[str] = None,
) -> RuntimeTask:
    req = dict(request or {})
    subject = str(req.get("subject") or "").strip()
    edu_level = str(req.get("edu_level") or "").strip()
    query = str(req.get("query") or "").strip()
    if not query:
        raise RunnerError("query_required", status_code=400)

    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    limit = _clamp_int(req.get("limit"), default=30, min_v=1, max_v=200)
    max_pages = _clamp_int(req.get("max_pages"), default=2, min_v=1, max_v=50)
    min_quality_score = _clamp_int(req.get("min_quality_score"), default=0, min_v=0, max_v=100)
    difficulty_value_min = _clamp_float(req.get("difficulty_value_min"), default=None, min_v=0.0, max_v=1.0)
    difficulty_value_max = _clamp_float(req.get("difficulty_value_max"), default=None, min_v=0.0, max_v=1.0)
    if difficulty_value_min is not None and difficulty_value_max is not None and difficulty_value_min > difficulty_value_max:
        difficulty_value_min, difficulty_value_max = difficulty_value_max, difficulty_value_min
    require_difficulty_value = bool(req.get("require_difficulty_value")) and (
        difficulty_value_min is not None or difficulty_value_max is not None
    )

    task_id = str(req.get("task_id") or "").strip() or f"ql_crawl_{uuid.uuid4().hex[:12]}"

    async def runner_factory(task: RuntimeTask) -> None:
        try:
            await task_runtime.append_event(
                task,
                {
                    "type": "step",
                    "step": {
                        "id": "crawl",
                        "title": "爬取入库",
                        "status": "running",
                        "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "toolName": "question_library_crawl",
                        "input": {
                            "taskId": task.task_id,
                            "subject": subject,
                            "edu_level": edu_level,
                            "query": query,
                            "difficulty": difficulty,
                            "question_type": question_type,
                            "limit": limit,
                            "max_pages": max_pages,
                            "min_quality_score": min_quality_score,
                            "difficulty_value_min": difficulty_value_min,
                            "difficulty_value_max": difficulty_value_max,
                            "require_difficulty_value": require_difficulty_value,
                        },
                    },
                },
            )

            crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)
            res = await crawler.search_by_keyword(
                keyword=query,
                subject=subject,
                edu_level=edu_level,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                max_pages=max_pages,
                min_quality_score=min_quality_score,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                require_difficulty_value=require_difficulty_value,
                parse_content=True,
            )
            if not bool(res.get("success")):
                raise RuntimeError(str(res.get("error") or "crawl_failed"))

            questions = res.get("questions") if isinstance(res.get("questions"), list) else []
            total = len(questions)
            inserted = 0
            qids: list[str] = []

            for i, q in enumerate(questions, start=1):
                if task.status != "running":
                    break
                if not isinstance(q, dict):
                    continue

                qid = str(q.get("question_id") or "").strip()
                stem = str(q.get("stem") or "").strip()
                if not qid or not stem:
                    continue

                await upsert_question_cache(
                    [
                        {
                            "question_id": qid,
                            "stem": stem,
                            "answer": str(q.get("answer") or "").strip(),
                            "analysis": str(q.get("analysis") or "").strip(),
                            "difficulty": str(q.get("difficulty") or "").strip(),
                            "question_type": str(q.get("question_type") or "").strip(),
                            "source": str(q.get("source") or "").strip(),
                            "date": str(q.get("date") or "").strip(),
                        }
                    ]
                )
                await upsert_question_library_items(
                    user_id=user_id,
                    items=[{"question_id": qid, "subject": subject, "origin": "crawled"}],
                )

                inserted += 1
                qids.append(qid)

                await task_runtime.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "crawled",
                                "hidden": False,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = int((i / max(1, total)) * 100)
                await task_runtime.append_event(task, {"type": "progress", "data": {"progress": pct}})

            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                return

            await task_runtime.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "inserted": inserted,
                        "subject": subject,
                        "count": len(qids),
                        "question_ids": qids,
                    },
                },
            )
            await task_runtime.complete_task(task)
        except asyncio.CancelledError:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task cancelled")
            else:
                async with task.cond:
                    task.cond.notify_all()
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception("question_library_import_runner_failed", extra={"task_id": task.task_id})
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_crawl",
        title=f"题库抓取：{subject or query or 'crawl'}",
        request=req,
        runner_factory=runner_factory,
        parent_task_id=parent_task_id,
    )


async def create_media_import_task(
    *,
    user_id: str,
    request: Dict[str, Any],
    parent_task_id: Optional[str] = None,
) -> RuntimeTask:
    req = dict(request or {})
    if not is_llm_configured(scope="chat"):
        raise RunnerError("llm_not_configured", status_code=500)

    subject = str(req.get("subject") or "").strip()
    if not subject:
        raise RunnerError("subject_required", status_code=400)

    topic = str(req.get("topic") or "").strip() or "图片/PDF 录入"
    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    count = _clamp_int(req.get("count"), default=10, min_v=1, max_v=30)
    task_id = safe_media_import_task_id(str(req.get("task_id") or "").strip())
    max_pdf_pages = _clamp_int(req.get("max_pdf_pages"), default=12, min_v=1, max_v=30)
    max_images = _clamp_int(req.get("max_images"), default=12, min_v=1, max_v=30)

    raw_files = req.get("files") if isinstance(req.get("files"), list) else []
    file_refs: List[MediaFileRef] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        filename = str(item.get("filename") or "").strip()
        content_type = str(item.get("content_type") or "").strip()
        if not path:
            continue
        resolved = Path(path).resolve()
        if not resolved.exists() or not resolved.is_file():
            continue
        file_refs.append(MediaFileRef(path=resolved, filename=filename or resolved.name, content_type=content_type))
    if not file_refs:
        raise RunnerError("files_required", status_code=400)

    session_id = str(req.get("session_id") or "").strip() or new_session_id()
    preview_id = str(req.get("preview_id") or "").strip() or new_preview_id()
    agent_spec = build_agent_run_spec_for_task(task_type="question_library_media_import", request=req)

    current_session = _ensure_session(
        session_id=session_id,
        user_id=user_id,
        preview_id=preview_id,
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        mode="standard",
        count=count,
        use_study_archive=False,
        use_reference_questions=False,
        reference_source="any",
        reference_year_range="all",
        grade_id="",
        textbook_version_id="",
        knowledge_point_ids=[],
        knowledge_points=[],
        task_id=task_id,
        stream_reasoning=False,
    )
    current_session["status"] = "running"
    current_session["source_type"] = "media_import"
    save_session(current_session)

    def _save_snapshot(*, session_status: str, preview_status: str, drafts: List[dict]) -> None:
        session = load_session(session_id) or {}
        if isinstance(session, dict):
            session = dict(session)
            session["status"] = session_status
            session["source_type"] = "media_import"
            session["draft_questions"] = normalize_draft_questions(drafts)
            save_session(session)

        save_preview(
            {
                "preview_id": preview_id,
                "session_id": session_id,
                "mode": "standard",
                "status": preview_status,
                "user_id": str(user_id or "").strip(),
                "task_id": task_id,
                "subject": subject,
                "topic": topic,
                "difficulty": difficulty,
                "question_type": question_type,
                "use_reference_questions": False,
                "reference_source": "any",
                "reference_year_range": "all",
                "source_type": "media_import",
                "draft_questions": normalize_draft_questions(drafts),
            }
        )

    async def runner_factory(task: RuntimeTask) -> None:
        drafts: List[dict] = []
        try:
            await task_runtime.append_event(
                task,
                {
                    "type": "step",
                    "step": {
                        "id": "media_import",
                        "title": "图片/PDF 录入",
                        "status": "running",
                        "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "toolName": "question_library_media_import",
                        "input": {
                            "taskId": task.task_id,
                            "subject": subject,
                            "topic": topic,
                            "difficulty": difficulty,
                            "question_type": question_type,
                            "count": count,
                            "files": [ref.filename for ref in file_refs],
                        },
                    },
                },
            )
            await task_runtime.append_event(
                task,
                {
                    "type": "progress",
                    "data": {"progress": 10, "stage": "convert_media", "stage_label": "转换图片"},
                },
            )

            pages = load_all_media_pages(file_refs, max_pdf_pages=max_pdf_pages, max_images=max_images)
            if not pages:
                raise MediaImportError("no_image_pages")
            await task_runtime.append_event(
                task,
                {
                    "type": "progress",
                    "data": {
                        "progress": 35,
                        "stage": "vision_extract",
                        "stage_label": "识别试题",
                        "stats": {"image_count": len(pages)},
                    },
                },
            )

            source_diagrams = await publish_media_pages_for_preview(pages, user_id=user_id)
            questions = await extract_questions_from_media_pages(
                pages=pages,
                subject=subject,
                topic=topic,
                difficulty=difficulty,
                question_type=question_type,
                max_questions=count,
            )
            if not questions:
                raise MediaImportError("no_questions_extracted")

            for item in questions[:count]:
                drafts.append(
                    {
                        "question_id": build_media_question_id(suffix=uuid.uuid4().hex[:8]),
                        "stem": str(item.get("stem") or "").strip(),
                        "answer": str(item.get("answer") or "").strip(),
                        "analysis": str(item.get("analysis") or "").strip(),
                        "keep": True,
                        "review_status": "pending_review",
                        **({"diagrams": source_diagrams} if source_diagrams else {}),
                    }
                )

            _save_snapshot(session_status="pending_review", preview_status="pending_review", drafts=drafts)
            await task_runtime.append_event(
                task,
                {
                    "type": "progress",
                    "data": {
                        "progress": 96,
                        "stage": "pending_review",
                        "stage_label": "待审核",
                        "stats": {"draft_count": len(drafts)},
                    },
                },
            )
            await task_runtime.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "session_id": session_id,
                        "preview_id": preview_id,
                        "subject": subject,
                        "topic": topic,
                        "difficulty": difficulty,
                        "question_type": question_type,
                        "use_study_archive": False,
                        "count": len(drafts),
                        "draft_questions": drafts,
                    },
                },
            )
            await task_runtime.complete_task(
                task,
                result={"success": True, "session_id": session_id, "preview_id": preview_id, "count": len(drafts)},
            )
        except asyncio.CancelledError:
            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                raise
            await task_runtime.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            if drafts:
                try:
                    _save_snapshot(session_status="partial_failure", preview_status="pending_review", drafts=drafts)
                except Exception:
                    logger.warning(
                        "question_library_media_import_snapshot_failed",
                        extra={"task_id": task.task_id, "user_id": user_id},
                        exc_info=True,
                    )
            logger.exception("question_library_media_import_failed", extra={"task_id": task.task_id, "user_id": user_id})
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_media_import",
        title=f"图片/PDF 录入：{subject} {topic}".strip(),
        request=req,
        runner_factory=runner_factory,
        meta=agentic_task_meta(agent_spec),
        starter_event=build_agentic_starter_event(spec=agent_spec, title="开始图片/PDF 录入", tool_name="question_library_media_import")
        if agent_spec is not None
        else None,
        parent_task_id=parent_task_id,
    )


async def create_score_task(
    *,
    user_id: str,
    request: Dict[str, Any],
    parent_task_id: Optional[str] = None,
) -> RuntimeTask:
    req = dict(request or {})
    if not is_codex_runtime_agent_runtime() and not is_llm_configured():
        raise RunnerError("llm_not_configured", status_code=500)

    subject = str(req.get("subject") or "").strip()
    if not subject:
        raise RunnerError("subject_required", status_code=400)

    limit = _clamp_int(req.get("limit"), default=50, min_v=1, max_v=500)
    batch_size = _clamp_int(req.get("batch_size"), default=50, min_v=1, max_v=50)
    only_unscored = bool(req.get("only_unscored"))
    task_id = str(req.get("task_id") or "").strip() or f"ql_score_{uuid.uuid4().hex[:12]}"

    threshold = _clamp_int(os.getenv("QUESTION_LIBRARY_HIDE_THRESHOLD") or 70, default=70, min_v=0, max_v=100)
    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"
    agent_spec = build_agent_run_spec_for_task(task_type="question_library_score", request=req)

    async def runner_factory(task: RuntimeTask) -> None:
        if is_codex_runtime_agent_runtime():
            handled = await run_codex_runtime_task(
                task,
                user_id=user_id,
                task_type="question_library_score",
                final_event_type="done",
            )
            if handled or not legacy_agent_fallback_enabled():
                return

        try:
            await task_runtime.append_event(task, {"type": "progress", "data": {"progress": 5, "stage": "Load"}})

            batch = await list_question_library_items(
                user_id=user_id,
                subject=subject,
                origin="crawled",
                hidden="0",
                limit=min(200, max(50, limit)),
                offset=0,
                sort="updated_at",
                order="desc",
            )
            items = batch.get("items") if isinstance(batch, dict) else []
            if not isinstance(items, list):
                items = []

            qids: list[str] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                qid = str(it.get("question_id") or "").strip()
                if not qid:
                    continue
                depth = extract_thinking_depth(it.get("ai_dimensions_json") or "")
                if only_unscored and it.get("ai_score") is not None and depth.get("score") is not None:
                    continue
                qids.append(qid)
                if len(qids) >= limit:
                    break

            if not qids:
                await task_runtime.append_event(
                    task,
                    {"type": "done", "data": {"success": True, "scored": 0, "hidden": 0, "subject": subject, "count": 0}},
                )
                await task_runtime.complete_task(task)
                return

            cache = await get_question_cache(question_ids=qids)
            scored = 0
            hidden_n = 0
            total = len(qids)
            method_context = await list_thinking_method_stats(user_id=user_id, subject=subject, limit=5000)
            await task_runtime.append_event(
                task,
                {
                    "type": "progress",
                    "data": {
                        "progress": 10,
                        "stage": "Score",
                        "batch_size": batch_size,
                        "method_families": len(method_context),
                    },
                },
            )

            processed = 0
            for start in range(0, len(qids), batch_size):
                if task.status != "running":
                    break
                chunk_qids = qids[start : start + batch_size]
                questions: list[dict] = []
                for qid in chunk_qids:
                    cached = cache.get(qid) or {}
                    stem = str(cached.get("stem") or "").strip()
                    if not stem:
                        continue
                    questions.append(
                        {
                            "question_id": qid,
                            "stem": stem,
                            "answer": str(cached.get("answer") or "").strip(),
                            "analysis": str(cached.get("analysis") or "").strip(),
                            "difficulty": str(cached.get("difficulty") or "").strip(),
                            "question_type": str(cached.get("question_type") or "").strip(),
                            "knowledge_point": str(cached.get("knowledge_point") or "").strip(),
                        }
                    )
                if not questions:
                    continue

                batch_res = await score_question_batch_with_thinking_depth(
                    subject=subject,
                    questions=questions,
                    model=model,
                    method_context=method_context,
                )
                score_items = [x for x in (batch_res.get("items") or []) if isinstance(x, dict)]
                method_context = merge_method_context(
                    method_context,
                    [x for x in (batch_res.get("method_summary") or []) if isinstance(x, dict)],
                    max_families=120,
                )

                stem_by_id = {str(q.get("question_id") or "").strip(): str(q.get("stem") or "").strip() for q in questions}
                for res in score_items:
                    if task.status != "running":
                        break
                    qid = str(res.get("question_id") or "").strip()
                    if not qid:
                        continue
                    stem = stem_by_id.get(qid, "")
                    overall = int(res.get("overall_score") or 0)
                    verdict = str(res.get("verdict") or "").strip()
                    dims = list(res.get("dimensions") or [])
                    summary = str(res.get("summary") or "").strip()
                    depth = extract_thinking_depth(dims)

                    await apply_score_and_hide(
                        user_id=user_id,
                        question_id=qid,
                        overall_score=overall,
                        verdict=verdict,
                        dimensions=[x for x in dims if isinstance(x, dict)],
                        summary=summary,
                        threshold=threshold,
                    )

                    scored += 1
                    processed += 1
                    if overall < threshold:
                        hidden_n += 1

                    await task_runtime.append_event(
                        task,
                        {
                            "type": "item_saved",
                            "data": {
                                "item": {
                                    "question_id": qid,
                                    "subject": subject,
                                    "origin": "crawled",
                                    "ai_score": overall,
                                    "ai_verdict": verdict,
                                    "ai_dimensions_json": json.dumps(dims, ensure_ascii=False),
                                    "ai_summary": summary,
                                    "thinking_depth_score": depth.get("score"),
                                    "thinking_method_family": depth.get("method_family") or "",
                                    "thinking_method_rarity": depth.get("method_rarity") or "",
                                    "thinking_method_count": depth.get("similar_method_count"),
                                    "hidden": overall < threshold,
                                    "stem": stem,
                                }
                            },
                        },
                    )

                    pct = 10 + int((processed / max(1, total)) * 88)
                    await task_runtime.append_event(
                        task,
                        {
                            "type": "progress",
                            "data": {
                                "progress": min(98, pct),
                                "stage": "Score",
                                "batch_size": batch_size,
                                "method_families": len(method_context),
                            },
                        },
                    )

            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                return

            await task_runtime.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "subject": subject,
                        "count": scored,
                        "scored": scored,
                        "hidden": hidden_n,
                        "threshold": threshold,
                        "batch_size": batch_size,
                        "method_summary": method_context,
                    },
                },
            )
            await task_runtime.complete_task(task)
        except asyncio.CancelledError:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task cancelled")
            else:
                async with task.cond:
                    task.cond.notify_all()
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception("question_library_score_runner_failed", extra={"task_id": task.task_id})
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_score",
        title=f"题库评分：{subject or 'score'}",
        request=req,
        runner_factory=runner_factory,
        meta=agentic_task_meta(agent_spec),
        starter_event=build_agentic_starter_event(spec=agent_spec, title="开始题库评分", tool_name="question_library_score")
        if agent_spec is not None
        else None,
        parent_task_id=parent_task_id,
    )


async def create_generate_task(
    *,
    user_id: str,
    request: Dict[str, Any],
    parent_task_id: Optional[str] = None,
) -> RuntimeTask:
    req = dict(request or {})
    if not is_codex_runtime_agent_runtime() and not is_llm_configured():
        raise RunnerError("llm_not_configured", status_code=500)

    subject = str(req.get("subject") or "").strip()
    topic_raw = str(req.get("topic") or "").strip()
    if not subject:
        raise RunnerError("subject_required", status_code=400)
    if not topic_raw:
        raise RunnerError("topic_required", status_code=400)

    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    if not question_type:
        inferred = infer_question_type_from_topic(topic_raw)
        if inferred:
            question_type = inferred

    count = _clamp_int(req.get("count"), default=5, min_v=1, max_v=10)
    mode = str(req.get("mode") or "standard").strip() or "standard"
    if mode not in {"standard", "infinite"}:
        mode = "standard"
    append_mode = bool(req.get("append"))
    stream_reasoning = bool(req.get("stream_reasoning"))
    use_archive = bool(req.get("use_study_archive"))
    use_reference_questions = bool(req.get("use_reference_questions"))
    reference_source = str(req.get("reference_source") or "any").strip() or "any"
    if reference_source not in {"any", "gaokao", "mock", "joint"}:
        reference_source = "any"
    reference_year_range = str(req.get("reference_year_range") or "all").strip() or "all"
    if reference_year_range not in {"all", "3", "5"}:
        reference_year_range = "all"
    session_id = str(req.get("session_id") or "").strip()
    grade_id = str(req.get("grade_id") or "").strip()
    textbook_version_id = str(req.get("textbook_version_id") or "").strip()
    knowledge_point_ids = [str(item or "").strip() for item in (req.get("knowledge_point_ids") or []) if str(item or "").strip()]
    knowledge_points = [str(item or "").strip() for item in (req.get("knowledge_points") or []) if str(item or "").strip()]

    task_id = str(req.get("task_id") or "").strip() or f"ql_gen_{uuid.uuid4().hex[:12]}"
    topic_key = normalize_topic_key(topic_raw) or topic_raw
    agent_spec = build_agent_run_spec_for_task(task_type="question_library_generate", request=req)

    existing_session = load_session(session_id) if session_id else None
    if session_id and existing_session and str(existing_session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise RunnerError("session_not_found", status_code=404)
    if not session_id:
        session_id = new_session_id()

    existing_preview = find_preview_by_session_id(user_id, session_id) if append_mode and session_id else None
    preview_id = (
        str((existing_session or {}).get("preview_id") or "").strip() if append_mode and isinstance(existing_session, dict) else ""
    ) or str((existing_preview or {}).get("preview_id") or "").strip() or new_preview_id()

    current_session = _ensure_session(
        session_id=session_id,
        user_id=user_id,
        preview_id=preview_id,
        subject=subject,
        topic=topic_raw,
        difficulty=difficulty,
        question_type=question_type,
        mode=mode,
        count=count,
        use_study_archive=use_archive,
        use_reference_questions=use_reference_questions,
        reference_source=reference_source,
        reference_year_range=reference_year_range,
        grade_id=grade_id,
        textbook_version_id=textbook_version_id,
        knowledge_point_ids=knowledge_point_ids,
        knowledge_points=knowledge_points,
        task_id=task_id,
        stream_reasoning=stream_reasoning,
    )
    current_session["status"] = "running"
    save_session(current_session)

    async def runner_factory(task: RuntimeTask) -> None:
        if is_codex_runtime_agent_runtime():
            handled = await run_codex_runtime_task(
                task,
                user_id=user_id,
                task_type="question_library_generate",
                final_event_type="done",
            )
            if handled or not legacy_agent_fallback_enabled():
                return

        draft_key_to_id: Dict[str, str] = {}
        progress_drafts = normalize_draft_questions(
            ((existing_preview or {}).get("draft_questions") if isinstance(existing_preview, dict) else [])
            or ((current_session or {}).get("draft_questions") if isinstance(current_session, dict) else [])
        )

        def _save_snapshot(*, session_status: str, preview_status: str, new_drafts: Optional[List[dict]] = None) -> None:
            nonlocal progress_drafts
            if new_drafts:
                progress_drafts = merge_drafts(progress_drafts, new_drafts)

            session = load_session(session_id) or {}
            if isinstance(session, dict):
                session = dict(session)
                session["status"] = str(session_status or "").strip() or session.get("status") or "running"
                session["draft_questions"] = progress_drafts
                session.setdefault("reasoning_blocks", [])
                save_session(session)

            save_preview(
                {
                    "preview_id": preview_id,
                    "session_id": session_id,
                    "mode": mode,
                    "status": str(preview_status or "").strip() or "running",
                    "user_id": str(user_id or "").strip(),
                    "task_id": str(task_id or "").strip(),
                    "subject": subject,
                    "topic": topic_raw,
                    "difficulty": difficulty,
                    "question_type": question_type,
                    "use_reference_questions": bool(use_reference_questions),
                    "reference_source": reference_source,
                    "reference_year_range": reference_year_range,
                    "study_markdown": "",
                    "draft_questions": progress_drafts,
                }
            )

        async def _emit_progress(stage_id: str, *, progress: float, stats: Optional[dict] = None, sample: Optional[dict] = None) -> None:
            payload = build_stage_progress_payload(
                stage_id,
                progress=float(progress),
                stats=stats if isinstance(stats, dict) else None,
                sample=sample if isinstance(sample, dict) else None,
            )
            await _emit_event(task, event_type="progress", data=payload, user_id=user_id, persist_task_id=task_id, progress=progress)

        async def _on_stage_event(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            phase = str(payload.get("phase") or "").strip()
            if not phase:
                return
            await _emit_progress(
                phase,
                progress=float(payload.get("progress") or 0.0),
                stats=payload.get("stats") if isinstance(payload.get("stats"), dict) else None,
                sample=payload.get("sample") if isinstance(payload.get("sample"), dict) else None,
            )

        async def _on_candidate_accepted(candidate: dict) -> None:
            if not isinstance(candidate, dict):
                return
            materialized, _ = _materialize_drafts(
                [candidate],
                existing_drafts=progress_drafts,
                draft_key_to_id=draft_key_to_id,
            )
            if materialized:
                _save_snapshot(session_status="running", preview_status="running", new_drafts=materialized)

        async def _on_reasoning_event(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            event_type = str(payload.get("type") or "").strip()
            if not event_type:
                return
            data = dict(payload)
            data.pop("type", None)

            if event_type in {"reasoning_delta", "reasoning_status"}:
                await _emit_event(task, event_type=event_type, data=data, user_id=user_id, persist_task_id=task_id)

            session = load_session(session_id) or {}
            if isinstance(session, dict):
                session = dict(session)
                if event_type == "reasoning_delta":
                    session = _merge_reasoning_block(session, task_id=task_id, payload=data)
                elif event_type == "reasoning_status":
                    session = _append_reasoning_status(session, task_id=task_id, payload=data)
                save_session(session)

        async def _stop_requested() -> bool:
            session = load_session(session_id) or {}
            if isinstance(session, dict) and bool(session.get("stop_requested")):
                return True
            return task.status != "running"

        try:
            _save_snapshot(session_status="running", preview_status="running")
            await _emit_progress("source_pack", progress=5.0, stats={"use_study_archive": bool(use_archive)})

            study_markdown = ""
            if use_archive:
                try:
                    archive = await get_latest_study_archive(user_id=user_id, subject=subject, topic=topic_key)
                except Exception:
                    logger.warning(
                        "question_library_latest_archive_lookup_failed",
                        extra={"task_id": task.task_id, "subject": subject, "topic": topic_key},
                        exc_info=True,
                    )
                    archive = None
                if not isinstance(archive, dict):
                    try:
                        archive = await get_latest_study_archive_for_subject(user_id=user_id, subject=subject)
                    except Exception:
                        logger.warning(
                            "question_library_subject_archive_lookup_failed",
                            extra={"task_id": task.task_id, "subject": subject},
                            exc_info=True,
                        )
                        archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "")

            source_pack = await build_source_pack(
                study_markdown,
                subject,
                topic_key,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=_on_reasoning_event,
            )
            await _emit_progress("source_pack", progress=10.0, stats={"study_markdown_chars": len(study_markdown)})

            await _emit_progress("curriculum_context", progress=12.0, stats={"knowledge_point_count": len(knowledge_points)})
            curriculum = await build_curriculum_context(
                subject=subject,
                topic=topic_key,
                knowledge_points=knowledge_points,
                grade_id=grade_id,
                textbook_version_id=textbook_version_id,
                study_markdown=study_markdown,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=_on_reasoning_event,
            )
            source_pack = enrich_source_pack_with_curriculum(source_pack, curriculum)
            source_pack["knowledge_points"] = list(knowledge_points)
            await _emit_progress(
                "curriculum_context",
                progress=14.0,
                stats={
                    "question_requirements": len(source_pack.get("question_requirements") or []),
                    "prerequisites": len(source_pack.get("prerequisites") or []),
                    "in_scope": len((source_pack.get("knowledge_scope") or {}).get("in_scope") or []),
                },
            )

            if use_reference_questions and not await _stop_requested():
                await _emit_progress("reference_crawl", progress=16.0, stats={"enabled": True})
                reference_result = await collect_reference_questions(
                    user_id=user_id,
                    subject=subject,
                    topic=topic_key,
                    difficulty=difficulty,
                    question_type=question_type,
                    knowledge_point_ids=knowledge_point_ids,
                    knowledge_points=knowledge_points,
                    desired_count=max(5, min(10, count + 3)),
                    reference_source=reference_source,
                    reference_year_range=reference_year_range,
                )
                reference_questions = (
                    [dict(item) for item in (reference_result.get("questions") or []) if isinstance(item, dict)]
                    if isinstance(reference_result, dict)
                    else []
                )
                await _emit_progress("reference_crawl", progress=18.0, stats={"reference_count": len(reference_questions)})

                await _emit_progress("reference_analysis", progress=22.0, stats={"enabled": True})
                if reference_questions:
                    reference_analysis = await analyze_reference_questions(
                        subject=subject,
                        topic=topic_key,
                        difficulty=difficulty,
                        question_type=question_type,
                        reference_questions=reference_questions,
                        stream_reasoning=stream_reasoning,
                        on_reasoning_event=_on_reasoning_event,
                    )
                    source_pack = enrich_source_pack_with_reference(source_pack, reference_analysis, reference_questions)
                    await _emit_progress("reference_analysis", progress=26.0, stats={"reference_count": len(reference_questions)})
                else:
                    await _emit_progress("reference_analysis", progress=26.0, stats={"skipped": True})

            batches = 0
            while True:
                if await _stop_requested():
                    break
                batches += 1
                try:
                    finals = await generate_questions(
                        source_pack=source_pack,
                        count=count,
                        difficulty=difficulty,
                        question_type=question_type,
                        user_id=user_id,
                        on_stage_event=_on_stage_event,
                        on_reasoning_event=_on_reasoning_event,
                        on_candidate_accepted=_on_candidate_accepted,
                        on_generation_snapshot=None,
                        stream_reasoning=stream_reasoning,
                        config=None,
                    )
                except Exception as exc:
                    await _on_reasoning_event(
                        {
                            "type": "reasoning_status",
                            "stage_id": "draft_realization",
                            "stage_label": get_question_generation_stage("draft_realization").label,
                            "mode": "trace",
                            "message": f"批次生成异常，将重试: {str(exc)[:220]}",
                        }
                    )
                    if mode == "infinite":
                        await asyncio.sleep(0.2)
                        continue
                    raise

                finals = [dict(x) for x in (finals or []) if isinstance(x, dict)]
                if not finals:
                    if mode == "infinite":
                        await asyncio.sleep(0.2)
                        continue
                    break

                materialized, _ = _materialize_drafts(finals, existing_drafts=progress_drafts, draft_key_to_id=draft_key_to_id)
                if materialized:
                    _save_snapshot(session_status="running", preview_status="running", new_drafts=materialized)

                if mode != "infinite":
                    break

            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                return

            final_session_status = "pending_review"
            if mode == "infinite":
                final_session_status = "stopped" if await _stop_requested() else "pending_review"
            _save_snapshot(session_status=final_session_status, preview_status="pending_review")

            await _emit_progress("pending_review", progress=96.0, stats={"draft_count": len(progress_drafts), "batches": batches})
            await _emit_event(
                task,
                event_type="done",
                data={
                    "success": True,
                    "session_id": session_id,
                    "preview_id": preview_id,
                    "subject": subject,
                    "topic": topic_key,
                    "difficulty": difficulty,
                    "question_type": question_type,
                    "use_study_archive": bool(use_archive),
                    "use_reference_questions": bool(use_reference_questions),
                    "reference_source": reference_source,
                    "reference_year_range": reference_year_range,
                    "count": len(progress_drafts),
                },
                user_id=user_id,
                persist_task_id=task_id,
            )
            await task_runtime.complete_task(
                task, result={"success": True, "session_id": session_id, "preview_id": preview_id}
            )
        except asyncio.CancelledError:
            # External controllers (e.g. app shutdown) may set a terminal status
            # before cancelling the runner. Respect that state and avoid
            # overwriting DB error payloads with a generic "Task cancelled".
            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                raise

            await task_runtime.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            try:
                # Preserve any accepted drafts for the review UI, even when the
                # pipeline fails mid-way (e.g., judge stage crash).
                if progress_drafts:
                    _save_snapshot(session_status="partial_failure", preview_status="pending_review")
                else:
                    _save_snapshot(session_status="failed", preview_status="pending_review")
            except Exception:
                logger.warning(
                    "question_library_snapshot_save_failed",
                    extra={"user_id": user_id, "task_id": task_id},
                    exc_info=True,
                )
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_generate",
        title=f"AI 出题：{subject} {topic_key}".strip(),
        request=req,
        runner_factory=runner_factory,
        meta=agentic_task_meta(agent_spec),
        starter_event=build_agentic_starter_event(spec=agent_spec, title="开始 AI 出题", tool_name="question_library_generate")
        if agent_spec is not None
        else None,
        parent_task_id=parent_task_id,
    )
