"""
OpenAI Function Calling 适配器。

将爬虫能力暴露为独立的 HTTP API，方便 OpenAI Function Calling / Agents 调用。
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/openai_adapter.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from crawler.zujuan_crawler import ZujuanCrawler
from database.models import get_paper, init_db, list_papers, save_paper
from backend.config import DEFAULT_SUBJECT
from backend.subjects import DEFAULT_DIFFICULTY, normalize_difficulty, resolve_subject


crawler: Optional[ZujuanCrawler] = None


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    global crawler
    if crawler:
        await crawler.close()


app = FastAPI(
    title="组卷助手 - OpenAI API",
    description="为 OpenAI Function Calling 提供的题目搜索 API",
    version="1.0.0",
    lifespan=lifespan,
)


async def get_crawler(subject: str = "") -> ZujuanCrawler:
    """获取或创建爬虫实例（支持学科切换）"""
    global crawler

    subject = (subject or DEFAULT_SUBJECT).strip()
    subject = resolve_subject(subject, strict=True)

    if crawler is None:
        crawler = ZujuanCrawler(subject=subject)
        await crawler.initialize()
    elif crawler.subject != subject:
        crawler.set_subject(subject)
    return crawler


class SearchByKeywordRequest(BaseModel):
    keyword: str
    subject: str = ""
    edu_level: str = ""
    limit: int = 20
    difficulty: str = ""
    question_type: str = ""
    max_pages: int = 3


class SearchByKnowledgeRequest(BaseModel):
    knowledge_point: str
    subject: str
    edu_level: str = ""
    limit: int = 20
    difficulty: str = ""
    question_type: str = ""
    max_pages: int = 3


class FilterQuestionsRequest(BaseModel):
    question_ids: List[str]
    difficulty: str = ""
    question_type: str = ""
    limit: int = 10


class CreatePaperRequest(BaseModel):
    paper_name: str
    question_ids: List[str]


@app.post("/api/search-by-keyword")
async def search_by_keyword(request: SearchByKeywordRequest) -> Dict[str, Any]:
    """通过关键词搜索题目（可用于 OpenAI Function Calling）"""
    subject = request.subject or DEFAULT_SUBJECT
    try:
        subject = resolve_subject(subject, edu_level=request.edu_level, strict=True)
        difficulty = normalize_difficulty(request.difficulty or DEFAULT_DIFFICULTY, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler_instance = await get_crawler(subject)
    result = await crawler_instance.search_by_keyword(
        keyword=request.keyword,
        subject=subject,
        edu_level=request.edu_level,
        limit=request.limit,
        difficulty=difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages,
        require_difficulty=True,
        strict_subject=True,
    )
    result["applied_subject"] = subject
    result["applied_difficulty"] = difficulty
    return result


@app.post("/api/search-by-knowledge")
async def search_by_knowledge(request: SearchByKnowledgeRequest) -> Dict[str, Any]:
    """通过知识点搜索题目（可用于 OpenAI Function Calling）"""
    try:
        subject = resolve_subject(request.subject, edu_level=request.edu_level, strict=True)
        difficulty = normalize_difficulty(request.difficulty or DEFAULT_DIFFICULTY, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler_instance = await get_crawler(subject)
    result = await crawler_instance.search_by_knowledge(
        knowledge_point=request.knowledge_point,
        subject=subject,
        edu_level=request.edu_level,
        limit=request.limit,
        difficulty=difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages,
        require_difficulty=True,
        strict_subject=True,
    )
    result["applied_subject"] = subject
    result["applied_difficulty"] = difficulty
    return result


@app.post("/api/filter-questions")
async def filter_questions(request: FilterQuestionsRequest) -> Dict[str, Any]:
    """筛选题目（可用于 OpenAI Function Calling）"""
    crawler_instance = await get_crawler()
    return await crawler_instance.filter_questions(
        question_ids=request.question_ids,
        difficulty=request.difficulty,
        question_type=request.question_type,
        limit=request.limit,
    )


@app.get("/api/question-info/{question_id}")
async def get_question_info(question_id: str) -> Dict[str, Any]:
    """获取题目信息（可用于 OpenAI Function Calling）"""
    crawler_instance = await get_crawler()
    return await crawler_instance.get_question_info(question_id)


@app.post("/api/create-paper")
async def create_paper(request: CreatePaperRequest) -> Dict[str, Any]:
    """创建试卷（仅保存题目编号，合规）"""
    try:
        questions = [{"question_id": qid} for qid in request.question_ids]
        paper_id = await save_paper(paper_name=request.paper_name, questions=questions)
        return {"success": True, "paper_id": paper_id, "message": f"试卷 '{request.paper_name}' 创建成功"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/papers")
async def get_papers(limit: int = 50) -> List[dict]:
    """获取试卷列表"""
    return await list_papers(limit=limit)


@app.get("/api/papers/{paper_id}")
async def get_paper_detail(paper_id: int) -> dict:
    """获取试卷详情"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return paper


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
