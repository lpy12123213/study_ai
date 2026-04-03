from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.paper_compose.analysis import analyze_paper
from backend.api.auth import require_auth
from backend.api.schemas import PaperCreate, PaperResponse
from backend.core.audit import AuditAction, audit_logger
from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive
from backend.database.models import delete_paper, get_paper, get_question_cache, list_papers, save_paper
from backend.database.repositories.tasks import append_task_event as db_append_task_event
from backend.database.repositories.tasks import update_task_status as db_update_task_status
from backend.database.repositories.tasks import upsert_task as db_upsert_task
from backend.paper_compose.compose_tasks import compose_tasks
from backend.paper_compose.export import export_paper as export_paper_doc
from backend.paper_compose.task_manager import PaperComposeTask
from backend.paper_compose.full_paper_workflow import generate_full_paper_events
from backend.paper_compose.workflow import compose_paper_events

router = APIRouter(dependencies=[Depends(require_auth)])
logger = get_logger(__name__)
_PAPER_ANALYSIS_CACHE: dict[tuple[int, str], dict] = {}


def clear_paper_analysis_cache() -> None:
    _PAPER_ANALYSIS_CACHE.clear()


def _infer_paper_source_mode(question_ids: list[str]) -> str:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    has_digits = any(x.isdigit() for x in ids)
    has_non_digits = any(not x.isdigit() for x in ids)
    if has_digits and has_non_digits:
        return "mixed"
    return "zujuan" if has_digits else "local"


async def _get_cached_paper_analysis(*, paper_id: int, paper: dict) -> dict:
    version = str(paper.get("updated_at") or paper.get("created_at") or "").strip()
    key = (int(paper_id), version)
    cached = _PAPER_ANALYSIS_CACHE.get(key)
    if isinstance(cached, dict):
        return dict(cached)

    loop = asyncio.get_running_loop()
    analysis = await loop.run_in_executor(None, analyze_paper, paper)
    if len(_PAPER_ANALYSIS_CACHE) >= 256:
        oldest_key = next(iter(_PAPER_ANALYSIS_CACHE.keys()), None)
        if oldest_key is not None:
            _PAPER_ANALYSIS_CACHE.pop(oldest_key, None)
    _PAPER_ANALYSIS_CACHE[key] = dict(analysis or {})
    return dict(analysis or {})


@router.post("/papers", response_model=dict)
async def create_paper(paper: PaperCreate, user: dict = Depends(require_auth)) -> dict:
    """创建试卷"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    try:
        q_dicts = paper.to_question_dicts()
        qids = [str((q or {}).get("question_id") or "").strip() for q in q_dicts if isinstance(q, dict)]
        mode = _infer_paper_source_mode(qids)
        if mode == "mixed":
            raise HTTPException(status_code=400, detail="paper_mixed_sources")

        paper_id = await save_paper(user_id=user_id, paper_name=paper.paper_name, questions=q_dicts)
        audit_logger.log(
            user_id=user_id,
            action=AuditAction.PAPER_CREATE,
            resource=f"/api/papers/{paper_id}",
            details={"paper_name": str(paper.paper_name or "").strip(), "question_count": len(qids), "source_mode": mode},
        )
        return {"success": True, "paper_id": paper_id, "message": f"试卷 '{paper.paper_name}' 创建成功"}
    except HTTPException:
        raise
    except ValueError as exc:
        # repository-level validation
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("paper_create_failed", extra={"user_id": user_id})
        raise HTTPException(status_code=500, detail="paper_create_failed") from exc


@router.get("/papers/{paper_id}", response_model=PaperResponse)
async def get_paper_info(
    paper_id: int,
    include_analysis: bool = Query(False),
    user: dict = Depends(require_auth),
) -> dict:
    """获取试卷信息"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    paper = await get_paper(user_id=user_id, paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    if include_analysis:
        paper["analysis"] = await _get_cached_paper_analysis(paper_id=paper_id, paper=paper)
    else:
        paper.pop("analysis", None)
    return paper


@router.get("/papers", response_model=List[dict])
async def get_papers_list(limit: int = 50, user: dict = Depends(require_auth)) -> List[dict]:
    """获取试卷列表"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return await list_papers(user_id=user_id, limit=limit)


@router.delete("/papers/{paper_id}")
async def remove_paper(paper_id: int, user: dict = Depends(require_auth)) -> dict:
    """删除试卷"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    success = await delete_paper(user_id=user_id, paper_id=paper_id)
    if not success:
        raise HTTPException(status_code=404, detail="试卷不存在")
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.PAPER_DELETE,
        resource=f"/api/papers/{int(paper_id)}",
        details={},
    )
    return {"success": True, "message": "试卷删除成功"}


@router.get("/papers/{paper_id}/download-link")
async def get_download_link(paper_id: int, user: dict = Depends(require_auth)) -> dict:
    """生成组卷网下载链接（合规：仅提供题目链接）"""
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    paper = await get_paper(user_id=user_id, paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    question_ids = [str(q.get("question_id") or "").strip() for q in paper.get("questions") or [] if isinstance(q, dict)]
    mode = _infer_paper_source_mode(question_ids)
    if mode != "zujuan":
        raise HTTPException(status_code=400, detail="paper_not_zujuan")

    cache = await get_question_cache(question_ids=question_ids)
    question_links = []
    for q in paper.get("questions") or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id") or "").strip()
        if not qid:
            continue
        if not qid.isdigit():
            continue
        # Prefer the stored source URL (includes correct bankId), fall back to a canonical URL by question_id.
        src = str(q.get("source_url") or "").strip()
        if not src:
            src = str((cache.get(qid) or {}).get("source_url") or "").strip()
        question_links.append(src or f"https://zujuan.xkw.com/q/{qid}")

    return {
        "success": True,
        "paper_name": paper["paper_name"],
        "question_count": len(question_ids),
        "question_ids": question_ids,
        "question_links": question_links,
        "instructions": [
            "1. 点击下方链接访问组卷网查看题目",
            "2. 在组卷网站上登录您的账号",
            "3. 将喜欢的题目加入组卷网的题库",
            "4. 使用组卷网的正规下载功能下载试卷",
        ],
    }


@router.post("/papers/{paper_id}/export")
async def export_paper(paper_id: int, payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> dict:
    """导出试卷为 Markdown/LaTeX/PDF（写入 `.local/media/generated/` 并返回下载链接）。"""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    paper = await get_paper(user_id=user_id, paper_id=paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    body = payload if isinstance(payload, dict) else {}
    fmt = str(body.get("format") or body.get("fmt") or "markdown").strip().lower()

    include_stem = bool(body.get("includeStem")) if "includeStem" in body else bool(body.get("include_stem"))
    include_answer = bool(body.get("includeAnswer")) if "includeAnswer" in body else bool(body.get("include_answer"))
    include_analysis = (
        bool(body.get("includeAnalysis")) if "includeAnalysis" in body else bool(body.get("include_analysis"))
    )

    try:
        out = await export_paper_doc(
            paper,
            user_id=user_id,
            fmt=fmt,
            include_stem=include_stem,
            include_answer=include_answer,
            include_analysis=include_analysis,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("paper_export_failed", extra={"user_id": user_id, "paper_id": int(paper_id)})
        raise HTTPException(status_code=500, detail="paper_export_failed") from exc

    if isinstance(out, dict) and out.get("success") is False:
        return {"success": False, **out}
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.PAPER_EXPORT,
        resource=f"/api/papers/{int(paper_id)}/export",
        details={
            "format": fmt,
            "include_stem": include_stem,
            "include_answer": include_answer,
            "include_analysis": include_analysis,
        },
    )
    return {"success": True, **(out if isinstance(out, dict) else {})}


@router.post("/papers/generate-full")
async def generate_full_paper(payload: Optional[dict] = None, user: dict = Depends(require_auth)) -> StreamingResponse:
    """一键 AI 生成整张试卷（返回 SSE 流）。"""

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")

    body = payload if isinstance(payload, dict) else {}
    req = dict(body)
    req.setdefault("taskId", uuid.uuid4().hex[:12])

    stream_reasoning = bool(req.get("stream_reasoning")) if "stream_reasoning" in req else bool(req.get("streamReasoning"))

    async def event_generator():
        async for event in generate_full_paper_events(req, user_id=user_id, stream_reasoning=stream_reasoning, on_reasoning_event=None):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


def _sse_headers() -> dict:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _run_compose_task(task: PaperComposeTask, *, user_id: str) -> None:
    """
    Run the compose workflow and append events into the task manager.
    """

    title = (
        str((task.request or {}).get("paperName") or (task.request or {}).get("paper_name") or "组卷任务").strip()
        or "组卷任务"
    )
    try:
        await db_upsert_task(
            user_id=user_id,
            task_id=task.task_id,
            task_type="paper_compose",
            title=title,
            status="running",
            progress=0.0,
            request=dict(task.request or {}),
            started_at=utcnow_naive(),
        )
        await db_append_task_event(
            user_id=user_id,
            task_id=task.task_id,
            event_type="step",
            payload={
                "step": {
                    "id": "task_started",
                    "title": "开始组卷任务",
                    "status": "running",
                    "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "toolName": "paper_compose",
                    "input": {"taskId": task.task_id},
                }
            },
        )
    except Exception:
        logger.exception("paper_compose_task_upsert_failed", extra={"task_id": task.task_id, "user_id": user_id})

    try:
        async for evt in compose_paper_events(task.request, user_id=user_id):
            if task.status != "running":
                break
            await compose_tasks.append_event(task, evt)

            try:
                payload = {k: evt.get(k) for k in ("step", "progress", "result", "error", "message") if k in evt}
                progress = None
                if "progress" in payload:
                    try:
                        progress = float(payload.get("progress") or 0.0)
                    except Exception:
                        progress = None
                await db_append_task_event(
                    user_id=user_id,
                    task_id=task.task_id,
                    event_type=str(evt.get("type") or "event"),
                    payload=payload,
                    progress=progress,
                )
            except Exception:
                logger.exception(
                    "paper_compose_task_event_write_failed",
                    extra={"task_id": task.task_id, "user_id": user_id, "event": evt},
                )

            kind = str(evt.get("type") or "")
            if kind == "result":
                await compose_tasks.complete_task(task)
                try:
                    result = evt.get("result") if isinstance(evt.get("result"), dict) else {"result": evt.get("result")}
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task.task_id,
                        status="completed",
                        progress=100.0,
                        result=result,
                        ended_at=utcnow_naive(),
                    )
                except Exception:
                    logger.exception(
                        "paper_compose_task_complete_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                    )
                return
            if kind == "error":
                await compose_tasks.fail_task(task, str(evt.get("error") or "compose_failed"))
                try:
                    await db_update_task_status(
                        user_id=user_id,
                        task_id=task.task_id,
                        status="failed",
                        error={"message": str(evt.get("error") or "compose_failed")},
                        ended_at=utcnow_naive(),
                    )
                except Exception:
                    logger.exception(
                        "paper_compose_task_fail_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                    )
                return
    except asyncio.CancelledError:
        await compose_tasks.fail_task(task, "Task cancelled")
        try:
            await db_update_task_status(
                user_id=user_id,
                task_id=task.task_id,
                status="canceled",
                error={"message": "Task cancelled"},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "paper_compose_task_cancel_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
            )
        raise
    except Exception as exc:  # pragma: no cover
        await compose_tasks.fail_task(task, str(exc))
        try:
            await db_update_task_status(
                user_id=user_id,
                task_id=task.task_id,
                status="failed",
                error={"message": str(exc)},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "paper_compose_task_error_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
            )
    finally:
        if task.status == "running":
            await compose_tasks.fail_task(task, "Task ended unexpectedly")
            try:
                await db_update_task_status(
                    user_id=user_id,
                    task_id=task.task_id,
                    status="failed",
                    error={"message": "Task ended unexpectedly"},
                    ended_at=utcnow_naive(),
                )
            except Exception:
                logger.exception(
                    "paper_compose_task_final_write_failed", extra={"task_id": task.task_id, "user_id": user_id}
                )


@router.post("/papers/compose")
async def compose_paper(payload: dict, user: dict = Depends(require_auth)) -> StreamingResponse:
    """
    Blueprint-based paper composing (teacher-side) with SSE streaming.

    Frontend expects events shaped like:
    - {type:'step', step: TaskStep}
    - {type:'progress', progress:number}
    - {type:'result', result: Paper}
    - {type:'error', error:string}
    """
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")

    task_id = str(payload.get("taskId") or payload.get("task_id") or "").strip()
    if not task_id:
        task_id = f"compose-{uuid.uuid4().hex[:12]}"
        payload["taskId"] = task_id

    async def runner_factory(task: PaperComposeTask):
        await _run_compose_task(task, user_id=user_id)

    try:
        await compose_tasks.create_task(
            task_id=task_id,
            user_id=user_id,
            request=payload,
            runner_factory=runner_factory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in compose_tasks.stream(task_id, after_seq=0, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
