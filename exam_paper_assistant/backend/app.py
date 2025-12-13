"""
FastAPI后端服务
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import sys
from pathlib import Path
import asyncio
import json

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

from database.models import (
    init_db, save_paper, get_paper, list_papers,
    delete_paper, add_search_history,
    create_conversation, list_conversations, get_conversation,
    delete_conversation, update_conversation_title,
    add_message, get_messages
)
from crawler.zujuan_crawler import ZujuanCrawler

# Import from current directory
sys.path.insert(0, str(Path(__file__).parent))
from analysis_service import analyze_paper
from chat_service import chat_service
from subjects import get_all_subjects, get_subject_config

app = FastAPI(
    title="智能组卷辅助系统",
    description="基于AI的组卷网题目搜索和筛选系统",
    version="1.0.0"
)

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件路径
dist_path = Path(__file__).parent.parent / "frontend" / "dist"

# 全局爬虫实例
crawler = None


async def get_crawler():
    """获取或创建爬虫实例"""
    global crawler
    if crawler is None:
        crawler = ZujuanCrawler()
        await crawler.initialize()
    return crawler


# 启动和关闭事件
@app.on_event("startup")
async def startup_event():
    """启动时初始化数据库"""
    await init_db()
    print("数据库初始化完成")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理资源"""
    global crawler
    if crawler:
        await crawler.close()

# Pydantic模型
class QuestionItem(BaseModel):
    question_id: str
    type: Optional[str] = ""
    difficulty: Optional[str] = ""

class PaperCreate(BaseModel):
    paper_name: str
    questions: List[QuestionItem] 


class QuestionInfo(BaseModel):
    question_id: str
    order: Optional[int] = None
    type: Optional[str] = None
    difficulty: Optional[str] = None
    knowledge_point: Optional[str] = None
    source_url: Optional[str] = None

class AnalysisResult(BaseModel):
    difficulty_score: float
    radar_data: List[dict]
    ai_comment: str

class PaperResponse(BaseModel):
    paper_id: int
    paper_name: str
    created_at: str
    questions: List[QuestionInfo]
    analysis: Optional[AnalysisResult] = None


@app.post("/api/papers", response_model=dict)
async def create_paper(paper: PaperCreate):
    """创建试卷"""
    try:
        # Convert Pydantic models to dicts for the service layer
        q_dicts = [q.dict() for q in paper.questions]
        paper_id = await save_paper(
            paper_name=paper.paper_name,
            questions=q_dicts
        )
        return {
            "success": True,
            "paper_id": paper_id,
            "message": f"试卷 '{paper.paper_name}' 创建成功"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/papers/{paper_id}", response_model=PaperResponse)
async def get_paper_info(paper_id: int):
    """获取试卷信息"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    
    # Perform AI Analysis
    analysis = analyze_paper(paper)
    paper["analysis"] = analysis
    
    return paper


@app.get("/api/papers", response_model=List[dict])
async def get_papers_list(limit: int = 50):
    """获取试卷列表"""
    papers = await list_papers(limit=limit)
    return papers


@app.delete("/api/papers/{paper_id}")
async def remove_paper(paper_id: int):
    """删除试卷"""
    success = await delete_paper(paper_id)
    if not success:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return {"success": True, "message": "试卷删除成功"}


@app.get("/api/papers/{paper_id}/download-link")
async def get_download_link(paper_id: int):
    """生成组卷网下载链接"""
    paper = await get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    question_ids = [q["question_id"] for q in paper["questions"]]

    # 构建组卷网的题目查看链接
    question_links = [
        f"https://zujuan.xkw.com/11q{qid}.html" for qid in question_ids
    ]

    return {
        "success": True,
        "paper_name": paper["paper_name"],
        "question_count": len(question_ids),
        "question_ids": question_ids,
        "question_links": question_links,
        "instructions": [
            "1. 点击下方链接访问组卷网查看题目",
            "2. 在组卷网网站上登录您的账号",
            "3. 将喜欢的题目加入组卷网的题库",
            "4. 使用组卷网的正规下载功能下载试卷"
        ]
    }


# ============ 学科 API ============

@app.get("/api/subjects")
async def get_subjects_list():
    """获取支持的学科列表"""
    all_subjects = get_all_subjects()
    return {"subjects": all_subjects}


# ============ 对话 API ============

class ChatRequest(BaseModel):
    conversation_id: int
    message: str
    subject: Optional[str] = "高中数学"


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"


@app.get("/api/conversations")
async def get_conversations_list(limit: int = 50):
    """获取对话列表"""
    conversations = await list_conversations(limit=limit)
    return conversations


@app.post("/api/conversations")
async def create_new_conversation(data: ConversationCreate):
    """创建新对话"""
    conv_id = await create_conversation(title=data.title)
    return {"id": conv_id, "title": data.title}


@app.delete("/api/conversations/{conv_id}")
async def remove_conversation(conv_id: int):
    """删除对话"""
    success = await delete_conversation(conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"success": True}


@app.get("/api/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: int):
    """获取对话消息"""
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = await get_messages(conv_id)
    return {"conversation": conv, "messages": messages}


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    处理聊天请求，返回SSE流式响应
    支持学科选择
    """
    conv_id = request.conversation_id
    user_message = request.message
    subject = request.subject

    # 验证对话存在
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 保存用户消息
    await add_message(conv_id, "user", user_message)

    # 获取历史消息
    history = await get_messages(conv_id)
    # 移除最后一条（刚刚添加的用户消息）
    history = history[:-1]

    async def generate():
        collected_content = ""
        collected_tool_calls = []
        tool_results = []
        streaming_content = ""

        async for chunk in chat_service.chat(history, user_message, subject=subject):
            chunk_type = chunk.get("type")

            if chunk_type == "assistant":
                collected_content = chunk.get("content", "")
                if chunk.get("tool_calls"):
                    collected_tool_calls = chunk["tool_calls"]
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "tool_start":
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "tool_result":
                tool_results.append(chunk)
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "stream_start":
                # 流式输出开始
                streaming_content = ""
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "text_delta":
                # 流式文本片段
                streaming_content += chunk.get("content", "")
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "iteration":
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "assistant_final":
                # 保存助手消息（包含工具调用）
                if collected_tool_calls:
                    await add_message(
                        conv_id, "assistant", collected_content,
                        tool_calls=json.dumps(collected_tool_calls, ensure_ascii=False)
                    )
                    # 保存工具结果
                    for tr in tool_results:
                        await add_message(
                            conv_id, "tool",
                            json.dumps(tr["result"], ensure_ascii=False),
                            tool_call_id=tr["tool_call_id"]
                        )

                # 保存最终助手消息
                final_content = chunk.get("content", "")
                await add_message(conv_id, "assistant", final_content)

                # 更新对话标题（如果是第一条消息）
                if len(history) == 0:
                    title = user_message[:30] + ("..." if len(user_message) > 30 else "")
                    await update_conversation_title(conv_id, title)

                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

            elif chunk_type == "error":
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# 3. 静态页面 (SPA路由支持)
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    Serving Single Page Application
    如果是API请求已经在上面被拦截。
    如果是静态资源请求，已经在/assets被挂载。
    其他所有路径都返回index.html，交给前端路由处理。
    """
    # 排除 /api 开头的请求 (虽然上面已经定义了，但以防万一)
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    index_path = dist_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Frontend not found. Please run 'npm run build' in frontend directory."}


# 运行服务
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

