from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.schemas import PaperCreate, PaperResponse
from backend.analysis_service import analyze_paper
from backend.database.models import delete_paper, get_paper, list_papers, save_paper
from backend.paper_compose.compose_tasks import compose_tasks
from backend.paper_compose.task_manager import PaperComposeTask
from backend.paper_compose.workflow import compose_paper_events

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/papers", response_model=dict)
async def create_paper(paper: PaperCreate) -> dict:
    """创建试卷"""
    try:
        q_dicts = paper.to_question_dicts()
        paper_id = await save_paper(paper_name=paper.paper_name, questions=q_dicts)
        return {"success": True, "paper_id": paper_id, "message": f"试卷 '{paper.paper_name}' 创建成功"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/papers/{paper_id}", response_model=PaperResponse)
async def get_paper_info(paper_id: int) -> dict:
    """获取试卷信息"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    # analyze_paper() does network I/O (OpenRouter) synchronously; offload it
    # to a thread to avoid blocking the event loop.
    loop = asyncio.get_running_loop()
    analysis = await loop.run_in_executor(None, analyze_paper, paper)
    paper["analysis"] = analysis
    return paper


@router.get("/papers", response_model=List[dict])
async def get_papers_list(limit: int = 50) -> List[dict]:
    """获取试卷列表"""
    return await list_papers(limit=limit)


@router.delete("/papers/{paper_id}")
async def remove_paper(paper_id: int) -> dict:
    """删除试卷"""
    success = await delete_paper(paper_id)
    if not success:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return {"success": True, "message": "试卷删除成功"}


@router.get("/papers/{paper_id}/download-link")
async def get_download_link(paper_id: int) -> dict:
    """生成组卷网下载链接（合规：仅提供题目链接）"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    question_ids = [q["question_id"] for q in paper["questions"]]
    question_links = []
    for q in paper["questions"]:
        qid = q.get("question_id")
        if not qid:
            continue
        # Prefer the stored source URL (includes correct bankId), fall back to a canonical URL by question_id.
        question_links.append(q.get("source_url") or f"https://zujuan.xkw.com/q/{qid}")

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
    try:
        async for evt in compose_paper_events(task.request, user_id=user_id):
            if task.status != "running":
                break
            await compose_tasks.append_event(task, evt)

            kind = str(evt.get("type") or "")
            if kind == "result":
                await compose_tasks.complete_task(task)
                return
            if kind == "error":
                await compose_tasks.fail_task(task, str(evt.get("error") or "compose_failed"))
                return
    except asyncio.CancelledError:
        await compose_tasks.fail_task(task, "Task cancelled")
        raise
    except Exception as exc:  # pragma: no cover
        await compose_tasks.fail_task(task, str(exc))
    finally:
        if task.status == "running":
            await compose_tasks.fail_task(task, "Task ended unexpectedly")


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
    user_id = str((user or {}).get("user_id") or "").strip() or "anonymous"
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
