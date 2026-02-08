from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter, HTTPException

from backend.api.schemas import PaperCreate, PaperResponse
from backend.analysis_service import analyze_paper
from backend.database.models import delete_paper, get_paper, list_papers, save_paper

router = APIRouter()


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
