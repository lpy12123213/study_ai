"""
OpenAI Function Calling 适配器
将爬虫功能暴露为OpenAI Function Calling可以调用的API
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from crawler.zujuan_crawler import ZujuanCrawler
from database.models import save_paper, get_paper, list_papers
import asyncio

app = FastAPI(
    title="组卷助手 - OpenAI API",
    description="为OpenAI Codex提供的题目搜索API",
    version="1.0.0"
)

# 全局爬虫实例
crawler = None


async def get_crawler():
    """获取或创建爬虫实例"""
    global crawler
    if crawler is None:
        crawler = ZujuanCrawler()
        await crawler.initialize()
    return crawler


# Request/Response模型
class SearchByKeywordRequest(BaseModel):
    keyword: str
    subject: str = ""
    limit: int = 20
    difficulty: str = ""
    question_type: str = ""
    max_pages: int = 3


class SearchByKnowledgeRequest(BaseModel):
    knowledge_point: str
    subject: str
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


# API端点
@app.post("/api/search-by-keyword")
async def search_by_keyword(request: SearchByKeywordRequest):
    """
    通过关键词搜索题目

    这个API可以被OpenAI Function Calling调用
    """
    crawler = await get_crawler()
    result = await crawler.search_by_keyword(
        keyword=request.keyword,
        subject=request.subject,
        limit=request.limit,
        difficulty=request.difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages
    )
    return result


@app.post("/api/search-by-knowledge")
async def search_by_knowledge(request: SearchByKnowledgeRequest):
    """
    通过知识点搜索题目

    这个API可以被OpenAI Function Calling调用
    """
    crawler = await get_crawler()
    result = await crawler.search_by_knowledge(
        knowledge_point=request.knowledge_point,
        subject=request.subject,
        limit=request.limit,
        difficulty=request.difficulty,
        question_type=request.question_type,
        max_pages=request.max_pages
    )
    return result


@app.post("/api/filter-questions")
async def filter_questions(request: FilterQuestionsRequest):
    """
    筛选题目

    这个API可以被OpenAI Function Calling调用
    """
    crawler = await get_crawler()
    result = await crawler.filter_questions(
        question_ids=request.question_ids,
        difficulty=request.difficulty,
        question_type=request.question_type,
        limit=request.limit
    )
    return result


@app.get("/api/question-info/{question_id}")
async def get_question_info(question_id: str):
    """
    获取题目信息

    这个API可以被OpenAI Function Calling调用
    """
    crawler = await get_crawler()
    result = await crawler.get_question_info(question_id)
    return result


@app.post("/api/create-paper")
async def create_paper(request: CreatePaperRequest):
    """
    创建试卷

    这个API可以被OpenAI Function Calling调用
    """
    try:
        # 将question_ids列表转换为questions列表格式
        questions = [{"question_id": qid} for qid in request.question_ids]
        paper_id = await save_paper(
            paper_name=request.paper_name,
            questions=questions
        )
        return {
            "success": True,
            "paper_id": paper_id,
            "message": f"试卷 '{request.paper_name}' 创建成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/papers")
async def get_papers(limit: int = 50):
    """获取试卷列表"""
    papers = await list_papers(limit=limit)
    return papers


@app.get("/api/papers/{paper_id}")
async def get_paper_detail(paper_id: int):
    """获取试卷详情"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return paper


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理资源"""
    global crawler
    if crawler:
        await crawler.close()


if __name__ == "__main__":
    import uvicorn

    # 初始化数据库
    from database.models import init_db
    asyncio.run(init_db())

    uvicorn.run(
        "openai_adapter:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )
