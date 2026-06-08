from __future__ import annotations

import asyncio
import json
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api.auth import require_auth
from backend.api.middleware.rate_limit import SlidingWindowRateLimiter
from backend.api.schemas import PaperCreate, PaperResponse
from backend.core.audit import AuditAction, audit_logger
from backend.core.logging_utils import get_logger
from backend.database.repositories.question.papers import delete_paper, get_paper, list_papers, save_paper
from backend.database.repositories.question.question_cache import get_question_cache
from backend.generation.paper_compose.analysis import analyze_paper
from backend.generation.paper_compose.export import export_paper as export_paper_doc
from backend.generation.paper_compose.export import export_paper_bundle
from backend.shared.tasks import task_runtime
from backend.tasks import submit_generate_full_paper_task, submit_paper_compose_task

router = APIRouter(dependencies=[Depends(require_auth)])
logger = get_logger(__name__)
_PAPER_ANALYSIS_CACHE: dict[tuple[int, str], dict] = {}
_PAPER_ANALYSIS_CACHE_LOCK = asyncio.Lock()
_PAPER_DOWNLOAD_LINK_LIMITER = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("PAPER_DOWNLOAD_LINK_RATE_LIMIT_MAX") or "30"),
    window_s=float(os.getenv("PAPER_DOWNLOAD_LINK_RATE_LIMIT_WINDOW_S") or "60"),
    max_keys=int(os.getenv("PAPER_DOWNLOAD_LINK_RATE_LIMIT_MAX_KEYS") or "20000"),
)


def clear_paper_analysis_cache() -> None:
    _PAPER_ANALYSIS_CACHE.clear()


def _payload_bool(payload: dict, *keys: str, default: bool = False) -> bool:
    if not isinstance(payload, dict):
        return bool(default)
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        raw = str(value).strip().lower()
        if raw in {"", "0", "false", "no", "n", "off"}:
            return False
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        return bool(value)
    return bool(default)


def _infer_paper_source_mode(question_ids: list[str]) -> str:
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    has_digits = any(x.isdigit() for x in ids)
    has_non_digits = any(not x.isdigit() for x in ids)
    if has_digits and has_non_digits:
        return "hybrid"
    return "zujuan" if has_digits else "local"


async def _get_cached_paper_analysis(*, paper_id: int, paper: dict) -> dict:
    version = str(paper.get("updated_at") or paper.get("created_at") or "").strip()
    key = (int(paper_id), version)
    async with _PAPER_ANALYSIS_CACHE_LOCK:
        cached = _PAPER_ANALYSIS_CACHE.get(key)
        if isinstance(cached, dict):
            return dict(cached)

    loop = asyncio.get_running_loop()
    analysis = await loop.run_in_executor(None, analyze_paper, paper)
    async with _PAPER_ANALYSIS_CACHE_LOCK:
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

        paper_id = await save_paper(user_id=user_id, paper_name=paper.paper_name, questions=q_dicts)
        audit_logger.log(
            user_id=user_id,
            action=AuditAction.PAPER_CREATE,
            resource=f"/api/papers/{paper_id}",
            details={"paper_name": str(paper.paper_name or "").strip(), "question_count": len(qids), "source_mode": mode},
        )
        return {
            "success": True,
            "paper_id": paper_id,
            "source_mode": mode,
            "message": f"试卷 '{paper.paper_name}' 创建成功",
        }
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
    if not await _PAPER_DOWNLOAD_LINK_LIMITER.allow(f"paper_download_link:{user_id}"):
        raise HTTPException(status_code=429, detail="rate_limited")
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

    audit_logger.log(
        user_id=user_id,
        action=AuditAction.PAPER_DOWNLOAD_LINK,
        resource=f"/api/papers/{int(paper_id)}/download-link",
        details={
            "paper_id": int(paper_id),
            "paper_name": str(paper.get("paper_name") or ""),
            "question_count": len(question_ids),
            "question_ids": question_ids[:200],
        },
    )

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

    include_stem = _payload_bool(body, "includeStem", "include_stem")
    include_answer = _payload_bool(body, "includeAnswer", "include_answer")
    include_analysis = _payload_bool(body, "includeAnalysis", "include_analysis")
    split_bundle = _payload_bool(body, "splitBundle", "split_bundle", "split")

    try:
        if split_bundle:
            out = await export_paper_bundle(paper, user_id=user_id, fmt=fmt, split_bundle=True)
        else:
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
        raise HTTPException(status_code=500, detail=str(out.get("error") or "paper_export_failed"))
    audit_logger.log(
        user_id=user_id,
        action=AuditAction.PAPER_EXPORT,
        resource=f"/api/papers/{int(paper_id)}/export",
        details={
            "format": fmt,
            "include_stem": include_stem,
            "include_answer": include_answer,
            "include_analysis": include_analysis,
            "split_bundle": split_bundle,
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
    task = await submit_generate_full_paper_task(user_id=user_id, request=dict(body))

    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in task_runtime.stream(task.task_id, after_seq=0, heartbeat_s=heartbeat_s):
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

    try:
        task = await submit_paper_compose_task(user_id=user_id, request=dict(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    heartbeat_s = float(os.getenv("PAPER_COMPOSE_SSE_HEARTBEAT_S") or "4.0")

    async def event_generator():
        async for event in task_runtime.stream(task.task_id, after_seq=0, heartbeat_s=heartbeat_s):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )
