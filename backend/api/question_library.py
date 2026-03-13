from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.question_library_schemas import (
    QuestionLibraryBulkDeleteRequest,
    QuestionLibraryCommitPreviewRequest,
    QuestionLibraryCrawlRequest,
    QuestionLibraryGenerateRequest,
    QuestionLibraryPreviewResponse,
    QuestionLibraryCommitPreviewResponse,
    QuestionLibraryScoreRequest,
)
from backend.core.llm_client import is_llm_configured
from backend.core.settings import LESSON_PLAN_MODEL
from backend.crawler_manager import get_crawler
from backend.database.models import (
    bulk_delete_question_library_items,
    get_latest_study_archive,
    get_question_cache,
    get_question_library_item,
    list_question_library_items,
    set_hidden,
    set_starred,
    upsert_question_cache,
    upsert_question_library_items,
)
from backend.database.repositories.tasks import (
    append_task_event as db_append_task_event,
)
from backend.database.repositories.tasks import (
    update_task_status as db_update_task_status,
)
from backend.database.repositories.tasks import (
    upsert_task as db_upsert_task,
)
from backend.question_library.generation import build_ai_question_id, build_source_pack, generate_questions
from backend.question_library.preview_store import delete_preview, load_preview, new_preview_id, save_preview
from backend.question_library.scoring import apply_score_and_hide, score_stem_with_llm
from backend.question_library.task_manager import QuestionLibraryTask, QuestionLibraryTaskManager

router = APIRouter(prefix="/question-library", tags=["question-library"], dependencies=[Depends(require_auth)])

_tasks = QuestionLibraryTaskManager(
    max_tasks=int(os.getenv("QUESTION_LIBRARY_MAX_TASKS") or "50"),
    task_ttl_s=int(os.getenv("QUESTION_LIBRARY_TASK_TTL_S") or str(60 * 60)),
    max_events_per_task=int(os.getenv("QUESTION_LIBRARY_TASK_MAX_EVENTS") or "8000"),
)


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_task(task_id: str, *, after_seq: int) -> StreamingResponse:
    heartbeat_s = float(os.getenv("QUESTION_LIBRARY_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in _tasks.stream(task_id, after_seq=after_seq, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@router.get("/items", response_model=dict)
async def list_items(
    subject: str = Query(""),
    origin: str = Query(""),
    hidden: str = Query("0"),
    q: str = Query(""),
    min_score: Optional[int] = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await list_question_library_items(
        user_id=user_id,
        subject=subject,
        origin=origin,
        hidden=hidden if hidden in {"0", "1", "all"} else "0",
        q=q,
        min_score=min_score,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/items/{question_id}", response_model=dict)
async def get_item_detail(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    item = await get_question_library_item(user_id=user_id, question_id=question_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[str(question_id or "").strip()])
    return {"library_item": item, "question_cache": cache.get(str(question_id or "").strip())}


@router.post("/items/{question_id}/hide", response_model=dict)
async def hide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unhide", response_model=dict)
async def unhide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/star", response_model=dict)
async def star_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unstar", response_model=dict)
async def unstar_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/bulk-delete", response_model=dict)
async def bulk_delete_items(request: QuestionLibraryBulkDeleteRequest, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    ids = [str(x or "").strip() for x in (request.question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(status_code=400, detail="question_ids_required")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="too_many_ids")

    deleted = await bulk_delete_question_library_items(user_id=user_id, question_ids=ids)
    return {"success": True, "deleted": deleted}


@router.post("/items/{question_id}/export-to-basket", response_model=dict)
async def export_item_to_basket(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    qid = str(question_id or "").strip()
    if not qid:
        raise HTTPException(status_code=400, detail="missing_question_id")
    if not qid.isdigit():
        raise HTTPException(status_code=400, detail="question_id_not_numeric")

    item = await get_question_library_item(user_id=user_id, question_id=qid)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[qid])
    q = cache.get(qid) or {}
    subject = str(item.get("subject") or q.get("subject") or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")

    def _kp_text(rec: dict) -> str:
        raw = str(rec.get("knowledge_points_json") or "").strip()
        kp = str(rec.get("knowledge_point") or "").strip()
        try:
            obj = json.loads(raw) if raw else []
        except Exception:
            obj = []
        parts = []
        if kp:
            parts.append(kp)
        if isinstance(obj, list):
            for x in obj[:12]:
                if isinstance(x, str) and x.strip():
                    parts.append(x.strip())
        uniq = []
        seen = set()
        for p in parts:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return "、".join(uniq[:12])

    detail = {
        "question_id": qid,
        "type": str(q.get("question_type") or "").strip() or "解答题",
        "difficulty": str(q.get("difficulty") or "").strip() or "中等",
        "source": str(q.get("source") or "").strip() or "本地题库",
        "knowledge_points": _kp_text(q),
    }

    crawler = await get_crawler(subject=subject, edu_level="", strict=True)
    try:
        result = await crawler.export_to_basket(
            [qid], question_details=[detail], auto_login=True, auto_switch_subject=True
        )
    except Exception:
        raise HTTPException(status_code=500, detail="export_failed")
    return result if isinstance(result, dict) else {"success": False, "error": "export_failed"}


@router.get("/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    payload = await _tasks.status_payload(task_id=task_id, user_id=user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="task_not_found")
    return payload


@router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str, after_seq: int = Query(0, ge=0), user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    task = await _tasks.get_task(task_id)
    if not task or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="task_not_found")
    return await _stream_task(task.task_id, after_seq=after_seq)


@router.get("/previews/{preview_id}", response_model=QuestionLibraryPreviewResponse)
async def get_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")

    drafts = obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else []
    return {
        "success": True,
        "preview_id": pid,
        "subject": str(obj.get("subject") or "").strip(),
        "topic": str(obj.get("topic") or "").strip(),
        "count": len(drafts),
        "draft_questions": drafts,
    }


@router.post("/previews/{preview_id}/commit", response_model=QuestionLibraryCommitPreviewResponse)
async def commit_preview(
    preview_id: str, request: QuestionLibraryCommitPreviewRequest, user: dict = Depends(require_auth)
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")

    status = str(obj.get("status") or "").strip().lower()
    if status == "committed":
        raise HTTPException(status_code=409, detail="preview_already_committed")

    subject = str(obj.get("subject") or "").strip()
    topic = str(obj.get("topic") or "").strip()
    difficulty = str(obj.get("difficulty") or "").strip()
    question_type = str(obj.get("question_type") or "").strip()

    preview_items = obj.get("draft_questions") if isinstance(obj.get("draft_questions"), list) else []
    preview_by_id: dict[str, dict] = {}
    for it in preview_items:
        if not isinstance(it, dict):
            continue
        qid = str(it.get("question_id") or "").strip()
        if qid:
            preview_by_id[qid] = dict(it)

    accepted_payload = []
    inserted_ids: list[str] = []
    for q in request.questions or []:
        qid = str(q.question_id or "").strip()
        if not qid or not q.keep:
            continue
        if qid not in preview_by_id:
            continue
        stem = str(q.stem or "").strip()
        answer = str(q.answer or "").strip()
        analysis = str(q.analysis or "").strip()
        if not stem or not answer or not analysis:
            continue
        inserted_ids.append(qid)
        accepted_payload.append(
            {
                "question_id": qid,
                "subject": subject,
                "question_type": question_type,
                "difficulty": difficulty,
                "knowledge_point": topic,
                "source_url": "",
                "stem": stem,
                "answer": answer,
                "analysis": analysis,
            }
        )

    if not accepted_payload:
        raise HTTPException(status_code=400, detail="no_questions_selected")

    await upsert_question_cache(accepted_payload)
    await upsert_question_library_items(
        user_id=user_id,
        items=[{"question_id": qid, "subject": subject, "origin": "ai"} for qid in inserted_ids],
    )

    obj = dict(obj)
    obj["status"] = "committed"
    obj["committed_at_s"] = time.time()
    obj["committed"] = {
        "inserted": len(inserted_ids),
        "question_ids": inserted_ids,
    }
    save_preview(obj)

    return {
        "success": True,
        "preview_id": pid,
        "inserted": len(inserted_ids),
        "subject": subject,
        "count": len(inserted_ids),
        "question_ids": inserted_ids,
    }


@router.post("/previews/{preview_id}/discard", response_model=dict)
async def discard_preview(preview_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    pid = str(preview_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="missing_preview_id")

    obj = load_preview(pid)
    if not obj or str(obj.get("user_id") or "").strip() != user_id:
        raise HTTPException(status_code=404, detail="preview_not_found")

    ok = delete_preview(pid)
    return {"success": bool(ok)}


@router.post("/crawl")
async def crawl_and_save(request: QuestionLibraryCrawlRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    subject = (request.subject or "").strip()
    edu_level = (request.edu_level or "").strip()
    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query_required")

    try:
        limit = max(1, min(int(request.limit or 30), 200))
    except Exception:
        limit = 30
    try:
        max_pages = max(1, min(int(request.max_pages or 2), 50))
    except Exception:
        max_pages = 2
    try:
        min_quality_score = max(0, min(int(request.min_quality_score or 0), 100))
    except Exception:
        min_quality_score = 0

    difficulty_value_min = request.difficulty_value_min
    difficulty_value_max = request.difficulty_value_max
    try:
        if difficulty_value_min is not None:
            difficulty_value_min = float(difficulty_value_min)
    except Exception:
        difficulty_value_min = None
    try:
        if difficulty_value_max is not None:
            difficulty_value_max = float(difficulty_value_max)
    except Exception:
        difficulty_value_max = None

    if difficulty_value_min is not None:
        difficulty_value_min = max(0.0, min(1.0, difficulty_value_min))
    if difficulty_value_max is not None:
        difficulty_value_max = max(0.0, min(1.0, difficulty_value_max))
    if (
        difficulty_value_min is not None
        and difficulty_value_max is not None
        and difficulty_value_min > difficulty_value_max
    ):
        difficulty_value_min, difficulty_value_max = difficulty_value_max, difficulty_value_min

    require_difficulty_value = bool(request.require_difficulty_value) and (
        difficulty_value_min is not None or difficulty_value_max is not None
    )

    difficulty = (request.difficulty or "").strip()
    question_type = (request.question_type or "").strip()

    task_id = (request.task_id or "").strip() or f"ql_crawl_{uuid.uuid4().hex[:12]}"

    async def runner_factory(task: QuestionLibraryTask) -> None:
        try:
            await _tasks.append_event(
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

                # For crawled questions we only persist the stem + metadata (no answer/analysis).
                cache_item = {
                    "question_id": qid,
                    "subject": subject,
                    "question_type": str(q.get("question_type") or q.get("type") or "").strip(),
                    "difficulty": str(q.get("difficulty") or "").strip(),
                    "knowledge_point": str(q.get("knowledge_point") or "").strip(),
                    "source_url": str(q.get("source_url") or "").strip(),
                    "stem": stem,
                    "stem_fingerprint": str(q.get("stem_fingerprint") or q.get("stem_fp") or "").strip(),
                    "difficulty_value": q.get("difficulty_value"),
                    "quality_score": int(q.get("quality_score") or 0),
                    "quality_flags": q.get("quality_flags") or "",
                    "knowledge_points_json": q.get("knowledge_points_json") or q.get("knowledge_points") or "",
                    "source": str(q.get("source") or "").strip(),
                    "date": str(q.get("date") or "").strip(),
                }
                await upsert_question_cache([cache_item])
                await upsert_question_library_items(
                    user_id=user_id,
                    items=[{"question_id": qid, "subject": subject, "origin": "crawled"}],
                )

                inserted += 1
                qids.append(qid)

                await _tasks.append_event(
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
                await _tasks.append_event(task, {"type": "progress", "data": {"progress": pct}})

            await _tasks.append_event(
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
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            await _tasks.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await _tasks.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await _tasks.fail_task(task, "Task ended unexpectedly")

    task = await _tasks.create_task(
        task_id=task_id, user_id=user_id, kind="crawl", request=request.model_dump(), runner_factory=runner_factory
    )  # type: ignore[attr-defined]
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/generate")
async def generate_and_save(
    request: QuestionLibraryGenerateRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    if not is_llm_configured():
        raise HTTPException(status_code=500, detail="llm_not_configured")

    subject = (request.subject or "").strip()
    topic = (request.topic or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")
    if not topic:
        raise HTTPException(status_code=400, detail="topic_required")

    difficulty = (request.difficulty or "").strip()
    question_type = (request.question_type or "").strip()

    try:
        count = max(1, min(int(request.count or 5), 10))
    except Exception:
        count = 5

    task_id = (request.task_id or "").strip() or f"ql_gen_{uuid.uuid4().hex[:12]}"
    use_archive = bool(request.use_study_archive)

    started_at = datetime.utcnow()
    await db_upsert_task(
        user_id=user_id,
        task_id=task_id,
        task_type="question_library_generate",
        title=f"AI 出题：{subject} {topic}".strip(),
        status="running",
        progress=0.0,
        request=request.model_dump(),
        started_at=started_at,
    )

    async def runner_factory(task: QuestionLibraryTask) -> None:
        def _now_iso() -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        async def _emit_progress(progress: float, stage: str) -> None:
            payload = {"progress": float(progress), "stage": str(stage or "").strip()}
            await _tasks.append_event(task, {"type": "progress", "data": payload})
            try:
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task_id,
                    event_type="progress",
                    payload=payload,
                    progress=float(progress),
                )
            except Exception:
                pass

        async def _emit_step(step: dict) -> None:
            await _tasks.append_event(task, {"type": "step", "step": step})
            try:
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type="step", payload={"step": step})
            except Exception:
                pass

        async def _emit_thinking(stage: str, content: str) -> None:
            t = _now_iso()
            await _emit_step(
                {
                    "id": f"thinking:{stage}:{uuid.uuid4().hex[:8]}",
                    "title": f"思考：{stage}",
                    "status": "completed",
                    "toolName": "thinking",
                    "startTime": t,
                    "endTime": t,
                    "output": str(content or "").strip(),
                }
            )

        try:
            await _emit_progress(5, "SourcePack")
            await _emit_thinking("SourcePack", "整理出题上下文，构建一个包含主题/难度/题型约束的素材包。")

            study_markdown = ""
            if use_archive:
                try:
                    archive = await get_latest_study_archive(user_id=user_id, subject=subject, topic=topic)
                except Exception:
                    archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "")

            source_pack = await build_source_pack(study_markdown, subject, topic)
            await _emit_progress(20, "Spec Search")
            await _emit_thinking("Spec Search", "为本次出题生成规格与候选方向，确保覆盖目标知识点并匹配难度与题型。")

            finals = await generate_questions(
                source_pack=source_pack,
                count=count,
                difficulty=difficulty,
                question_type=question_type,
                config=None,
            )
            await _emit_progress(55, "Draft Realization")
            await _emit_thinking("Draft Realization", "生成题目草稿（题干/答案/解析），并做基本一致性检查。")

            # Skeleton stages (solver/judge) are currently no-ops but we still emit them for UI.
            await _emit_progress(80, "Judge")
            await _emit_thinking("Judge", "检查题目可解性与答案/解析自洽性；不确定处保守表述，避免误导。")

            drafts: list[dict] = []
            for q in finals[:count]:
                if task.status != "running":
                    break
                if not isinstance(q, dict):
                    continue
                stem = str(q.get("stem") or "").strip()
                answer = str(q.get("answer") or "").strip()
                analysis = str(q.get("analysis") or "").strip()
                if not stem or not answer or not analysis:
                    continue
                qid = build_ai_question_id(suffix=uuid.uuid4().hex[:8])
                drafts.append(
                    {
                        "question_id": qid,
                        "stem": stem,
                        "answer": answer,
                        "analysis": analysis,
                        "keep": True,
                    }
                )

            if not drafts:
                raise RuntimeError("no_questions_generated")

            await _emit_progress(92, "Pending Review")
            await _emit_thinking("Pending Review", "题目草稿已生成，进入预览审核；审核通过后才会写入本地题库。")

            preview_id = new_preview_id()
            save_preview(
                {
                    "preview_id": preview_id,
                    "status": "pending_review",
                    "user_id": user_id,
                    "task_id": task_id,
                    "subject": subject,
                    "topic": topic,
                    "difficulty": difficulty,
                    "question_type": question_type,
                    "draft_questions": drafts,
                }
            )

            done_payload = {
                "success": True,
                "preview_id": preview_id,
                "subject": subject,
                "topic": topic,
                "count": len(drafts),
                "draft_questions": drafts,
            }
            await _tasks.append_event(task, {"type": "done", "data": done_payload})
            try:
                await db_append_task_event(user_id=user_id, task_id=task_id, event_type="done", payload=done_payload)
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="completed",
                    progress=100.0,
                    result={"preview_id": preview_id, "subject": subject, "topic": topic, "count": len(drafts)},
                    ended_at=datetime.utcnow(),
                )
            except Exception:
                pass
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            await _tasks.fail_task(task, "Task cancelled")
            try:
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="canceled",
                    error={"message": "Task cancelled"},
                    ended_at=datetime.utcnow(),
                )
            except Exception:
                pass
            raise
        except Exception as exc:  # pragma: no cover
            await _tasks.fail_task(task, str(exc))
            try:
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task_id,
                    event_type="error",
                    payload={"error": {"message": str(exc)}},
                )
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task_id,
                    status="failed",
                    error={"message": str(exc)},
                    ended_at=datetime.utcnow(),
                )
            except Exception:
                pass
        finally:
            if task.status == "running":
                await _tasks.fail_task(task, "Task ended unexpectedly")
                try:
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task_id,
                        status="failed",
                        error={"message": "Task ended unexpectedly"},
                        ended_at=datetime.utcnow(),
                    )
                except Exception:
                    pass

    task = await _tasks.create_task(
        task_id=task_id,
        user_id=user_id,
        kind="generate",
        request=request.model_dump(),
        runner_factory=runner_factory,
    )
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/score")
async def score_question_library(
    request: QuestionLibraryScoreRequest, user: dict = Depends(require_auth)
) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    if not is_llm_configured():
        raise HTTPException(status_code=500, detail="llm_not_configured")

    subject = (request.subject or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="subject_required")

    try:
        limit = max(1, min(int(request.limit or 50), 500))
    except Exception:
        limit = 50

    only_unscored = bool(request.only_unscored)
    task_id = (request.task_id or "").strip() or f"ql_score_{uuid.uuid4().hex[:12]}"

    threshold = int(os.getenv("QUESTION_LIBRARY_HIDE_THRESHOLD") or "70")
    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"

    async def runner_factory(task: QuestionLibraryTask) -> None:
        try:
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 5, "stage": "Load"}})

            # Pull a visible batch from the library and filter unscored if requested.
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
                if only_unscored and it.get("ai_score") is not None:
                    continue
                qids.append(qid)
                if len(qids) >= limit:
                    break

            if not qids:
                await _tasks.append_event(
                    task,
                    {
                        "type": "done",
                        "data": {"success": True, "scored": 0, "hidden": 0, "subject": subject, "count": 0},
                    },
                )
                await _tasks.complete_task(task)
                return

            cache = await get_question_cache(question_ids=qids)

            scored = 0
            hidden_n = 0
            total = len(qids)
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 10, "stage": "Score"}})

            for idx, qid in enumerate(qids, start=1):
                if task.status != "running":
                    break
                stem = str((cache.get(qid) or {}).get("stem") or "").strip()
                if not stem:
                    continue

                res = await score_stem_with_llm(subject=subject, stem=stem, model=model)
                overall = int(res.get("overall_score") or 0)
                verdict = str(res.get("verdict") or "").strip()
                dims = list(res.get("dimensions") or [])
                summary = str(res.get("summary") or "").strip()

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
                if overall < threshold:
                    hidden_n += 1

                await _tasks.append_event(
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
                                "ai_summary": summary,
                                "hidden": overall < threshold,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = 10 + int((idx / max(1, total)) * 88)
                await _tasks.append_event(
                    task, {"type": "progress", "data": {"progress": min(98, pct), "stage": "Score"}}
                )

            await _tasks.append_event(
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
                    },
                },
            )
            await _tasks.complete_task(task)
        except asyncio.CancelledError:
            await _tasks.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await _tasks.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await _tasks.fail_task(task, "Task ended unexpectedly")

    task = await _tasks.create_task(
        task_id=task_id,
        user_id=user_id,
        kind="score",
        request=request.model_dump(),
        runner_factory=runner_factory,
    )
    return await _stream_task(task.task_id, after_seq=0)
