from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.question_library_schemas import (
    QuestionLibraryCrawlRequest,
    QuestionLibraryGenerateRequest,
    QuestionLibraryScoreRequest,
)
from backend.crawler_manager import get_crawler
from backend.core.llm_client import is_llm_configured
from backend.core.settings import LESSON_PLAN_MODEL
from backend.database.models import (
    get_latest_study_archive,
    get_question_cache,
    get_question_library_item,
    list_question_library_items,
    set_hidden,
    set_starred,
    upsert_question_cache,
    upsert_question_library_items,
)
from backend.question_library.generation import build_ai_question_id, build_source_pack, generate_questions
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
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
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
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
    item = await get_question_library_item(user_id=user_id, question_id=question_id)
    if not item:
        raise HTTPException(status_code=404, detail="not_found")

    cache = await get_question_cache(question_ids=[str(question_id or "").strip()])
    return {"library_item": item, "question_cache": cache.get(str(question_id or "").strip())}


@router.post("/items/{question_id}/hide", response_model=dict)
async def hide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unhide", response_model=dict)
async def unhide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/star", response_model=dict)
async def star_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unstar", response_model=dict)
async def unstar_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_starred(user_id=user_id, question_id=question_id, starred=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/export-to-basket", response_model=dict)
async def export_item_to_basket(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
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
        result = await crawler.export_to_basket([qid], question_details=[detail], auto_login=True, auto_switch_subject=True)
    except Exception:
        raise HTTPException(status_code=500, detail="export_failed")
    return result if isinstance(result, dict) else {"success": False, "error": "export_failed"}


@router.get("/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
    payload = await _tasks.status_payload(task_id=task_id, user_id=user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="task_not_found")
    return payload


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str, after_seq: int = Query(0, ge=0), user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
    task = await _tasks.get_task(task_id)
    if not task or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="task_not_found")
    return await _stream_task(task.task_id, after_seq=after_seq)


@router.post("/crawl")
async def crawl_and_save(request: QuestionLibraryCrawlRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"

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

    task = await _tasks.create_task(task_id=task_id, user_id=user_id, kind="crawl", request=request.model_dump(), runner_factory=runner_factory)  # type: ignore[attr-defined]
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/generate")
async def generate_and_save(request: QuestionLibraryGenerateRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"

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

    async def runner_factory(task: QuestionLibraryTask) -> None:
        try:
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 5, "stage": "SourcePack"}})

            study_markdown = ""
            if use_archive:
                try:
                    archive = await get_latest_study_archive(user_id=user_id, subject=subject, topic=topic)
                except Exception:
                    archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "")

            source_pack = await build_source_pack(study_markdown, subject, topic)
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 20, "stage": "Spec Search"}})

            finals = await generate_questions(
                source_pack=source_pack,
                count=count,
                difficulty=difficulty,
                question_type=question_type,
                config=None,
            )
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 55, "stage": "Draft Realization"}})

            # Skeleton stages (solver/judge) are currently no-ops but we still emit them for UI.
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 70, "stage": "Solver"}})
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 80, "stage": "Judge"}})
            await _tasks.append_event(task, {"type": "progress", "data": {"progress": 85, "stage": "Save"}})

            saved_ids: list[str] = []
            for idx, q in enumerate(finals[:count], start=1):
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

                await upsert_question_cache(
                    [
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
                    ]
                )
                await upsert_question_library_items(
                    user_id=user_id,
                    items=[{"question_id": qid, "subject": subject, "origin": "ai"}],
                )

                saved_ids.append(qid)
                await _tasks.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "ai",
                                "hidden": False,
                                "stem": stem,
                                "ai_score": None,
                                "ai_verdict": "",
                                "ai_summary": "",
                            }
                        },
                    },
                )

                pct = 85 + int((idx / max(1, count)) * 13)
                await _tasks.append_event(task, {"type": "progress", "data": {"progress": min(98, pct), "stage": "Save"}})

            if not saved_ids:
                raise RuntimeError("no_questions_generated")

            await _tasks.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "inserted": len(saved_ids),
                        "subject": subject,
                        "count": len(saved_ids),
                        "question_ids": saved_ids,
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
        kind="generate",
        request=request.model_dump(),
        runner_factory=runner_factory,
    )
    return await _stream_task(task.task_id, after_seq=0)


@router.post("/score")
async def score_question_library(request: QuestionLibraryScoreRequest, user: dict = Depends(require_auth)) -> StreamingResponse:
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"

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
                await _tasks.append_event(task, {"type": "progress", "data": {"progress": min(98, pct), "stage": "Score"}})

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
