"""
数据库模型 - 试卷/对话/画布等持久化。

注意：项目默认合规策略是“题库内容不对外展示/导出”，但为了提升组卷与审卷体验，
本项目允许在本地数据库中保存题干纯文本（不含答案/解析）。
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Float, delete, desc, func, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, selectinload
from datetime import datetime
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from pathlib import Path

Base = declarative_base()


class Paper(Base):
    """试卷表"""
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    paper_name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联题目
    questions = relationship("PaperQuestion", back_populates="paper", cascade="all, delete-orphan")


class PaperQuestion(Base):
    """试卷题目关联表（只存储题目编号）"""
    __tablename__ = "paper_questions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    question_id = Column(String(50), nullable=False)  # 题目编号
    question_order = Column(Integer)  # 题目顺序
    question_type = Column(String(50))  # 题型
    difficulty = Column(String(20))  # 难度
    knowledge_point = Column(String(200))  # 知识点
    source_url = Column(String(500))  # 题目来源URL

    # Optional local storage for the question stem (no answers/analysis).
    stem = Column(Text, default="")  # 题干纯文本（含 LaTeX 公式占位）
    stem_fingerprint = Column(String(32), default="")  # md5，用于去重/复用
    difficulty_value = Column(Float)  # 难度系数（越小越难）
    quality_score = Column(Integer, default=0)  # 0-100
    quality_flags = Column(Text, default="")  # JSON string list
    knowledge_points_json = Column(Text, default="")  # JSON string list
    source = Column(String(200), default="")  # 来源（如：xx年期末）
    date = Column(String(50), default="")  # 日期（如：2024/05）

    # 关联试卷
    paper = relationship("Paper", back_populates="questions")


class Blueprint(Base):
    """组卷蓝图（教师侧配置）"""

    __tablename__ = "blueprints"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    name = Column(String(200), nullable=False, default="")
    subject = Column(String(100), nullable=False, default="")
    topic = Column(String(200), nullable=False, default="")
    slots_json = Column(Text, nullable=False, default="[]")  # JSON: BlueprintSlot[]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SearchHistory(Base):
    """搜索历史记录"""
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True, index=True)
    search_type = Column(String(50))  # 搜索类型：keyword, knowledge等
    search_query = Column(String(500))  # 搜索内容
    result_count = Column(Integer)  # 结果数量
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """对话会话表"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联消息
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """消息表"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'tool'
    content = Column(Text)  # 消息内容
    tool_calls = Column(Text)  # JSON: 工具调用信息
    tool_call_id = Column(String(100))  # 工具调用ID（用于tool角色）
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联对话
    conversation = relationship("Conversation", back_populates="messages")


class CanvasBoard(Base):
    """学习画布（tldraw store snapshot 持久化）"""

    __tablename__ = "canvas_boards"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, default="新画布")
    subject = Column(String(100), default="")
    revision = Column(Integer, default=1)
    snapshot = Column(Text, default="")  # JSON serialized store snapshot
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship(
        "CanvasBoardVersion",
        back_populates="board",
        cascade="all, delete-orphan",
    )


class CanvasBoardVersion(Base):
    """学习画布版本快照"""

    __tablename__ = "canvas_board_versions"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("canvas_boards.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON serialized store snapshot
    created_at = Column(DateTime, default=datetime.utcnow)

    board = relationship("CanvasBoard", back_populates="versions")


# 数据库引擎和会话
# NOTE: this file lives under `backend/database/`, so we need to jump 2 levels
# to reach the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = PROJECT_ROOT / ".local"
LEGACY_DB_PATH = PROJECT_ROOT / "exam_papers.db"
DB_PATH = LOCAL_DIR / "exam_papers.db"

# Directory tidy: prefer `.local/exam_papers.db`, but gracefully fall back to the legacy location.
try:
    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        LEGACY_DB_PATH.replace(DB_PATH)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    DB_PATH = LEGACY_DB_PATH

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

async_session_maker = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """初始化数据库"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_migrate_db_schema)
    print("数据库初始化完成")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话"""
    async with async_session_maker() as session:
        yield session


# 数据库操作函数
async def save_paper(paper_name: str, questions: List[dict]) -> int:
    """
    保存试卷

    Args:
        paper_name: 试卷名称
        questions: 题目列表，每个元素包含 question_id, type, difficulty 等

    Returns:
        试卷ID
    """
    async with async_session_maker() as session:
        # 创建试卷
        paper = Paper(paper_name=paper_name)
        session.add(paper)
        await session.commit()
        await session.refresh(paper)

        # 添加题目
        for i, q_data in enumerate(questions):
            # 兼容旧格式（如果只是字符串列表）
            if isinstance(q_data, str):
                qid = q_data
                q_type = ""
                q_diff = ""
                q_knowledge = ""
                q_source_url = ""
                stem = ""
                stem_fp = ""
                difficulty_value = None
                quality_score = 0
                quality_flags = ""
                knowledge_points_json = ""
                source = ""
                date = ""
            else:
                qid = q_data.get("question_id")
                q_type = q_data.get("type") or q_data.get("question_type")
                q_diff = q_data.get("difficulty")
                q_knowledge = q_data.get("knowledge_point") or ""
                q_source_url = q_data.get("source_url") or ""
                stem = q_data.get("stem") or ""
                stem_fp = q_data.get("stem_fingerprint") or q_data.get("stem_fp") or ""
                difficulty_value = q_data.get("difficulty_value")
                quality_score = q_data.get("quality_score") or 0
                quality_flags = q_data.get("quality_flags") or ""
                knowledge_points_json = q_data.get("knowledge_points_json") or q_data.get("knowledge_points") or ""
                source = q_data.get("source") or ""
                date = q_data.get("date") or ""

                # Normalize JSON-like fields (store as string).
                if isinstance(quality_flags, list):
                    try:
                        quality_flags = json.dumps(quality_flags, ensure_ascii=False)
                    except Exception:
                        quality_flags = ""
                if isinstance(knowledge_points_json, list):
                    try:
                        knowledge_points_json = json.dumps(knowledge_points_json, ensure_ascii=False)
                    except Exception:
                        knowledge_points_json = ""

            paper_question = PaperQuestion(
                paper_id=paper.id,
                question_id=qid,
                question_order=i + 1,
                question_type=q_type,
                difficulty=q_diff,
                knowledge_point=q_knowledge,
                source_url=q_source_url,
                stem=stem,
                stem_fingerprint=stem_fp,
                difficulty_value=difficulty_value,
                quality_score=quality_score,
                quality_flags=quality_flags,
                knowledge_points_json=knowledge_points_json,
                source=source,
                date=date,
            )
            session.add(paper_question)

        await session.commit()
        return paper.id


async def get_paper(paper_id: int) -> dict:
    """
    获取试卷信息

    Args:
        paper_id: 试卷ID

    Returns:
        试卷信息字典
    """
    async with async_session_maker() as session:
        # 查询试卷
        result = await session.execute(
            select(Paper).where(Paper.id == paper_id)
        )
        paper = result.scalar_one_or_none()

        if not paper:
            return None

        # 查询关联的题目
        questions_result = await session.execute(
            select(PaperQuestion)
            .where(PaperQuestion.paper_id == paper_id)
            .order_by(PaperQuestion.question_order)
        )
        questions = questions_result.scalars().all()

        return {
            "paper_id": paper.id,
            "paper_name": paper.paper_name,
            "created_at": paper.created_at.isoformat(),
            "questions": [
                {
                    "question_id": q.question_id,
                    "order": q.question_order,
                    "type": q.question_type,
                    "difficulty": q.difficulty,
                    "knowledge_point": q.knowledge_point,
                    "source_url": q.source_url,
                    "stem": q.stem or "",
                }
                for q in questions
            ]
        }


async def list_papers(limit: int = 50) -> List[dict]:
    """
    列出所有试卷

    Args:
        limit: 返回数量限制

    Returns:
        试卷列表
    """
    async with async_session_maker() as session:
        # 使用 selectinload 预加载关系，避免懒加载问题
        result = await session.execute(
            select(Paper)
            .options(selectinload(Paper.questions))
            .order_by(Paper.created_at.desc())
            .limit(limit)
        )
        papers = result.scalars().all()

        return [
            {
                "paper_id": p.id,
                "paper_name": p.paper_name,
                "created_at": p.created_at.isoformat(),
                "question_count": len(p.questions)
            }
            for p in papers
        ]


async def delete_paper(paper_id: int) -> bool:
    """
    删除试卷

    Args:
        paper_id: 试卷ID

    Returns:
        是否删除成功
    """
    async with async_session_maker() as session:
        result = await session.execute(
            select(Paper).where(Paper.id == paper_id)
        )
        paper = result.scalar_one_or_none()

        if not paper:
            return False

        await session.delete(paper)
        await session.commit()
        return True


async def add_search_history(search_type: str, search_query: str, result_count: int):
    """
    添加搜索历史记录

    Args:
        search_type: 搜索类型
        search_query: 搜索内容
        result_count: 结果数量
    """
    async with async_session_maker() as session:
        history = SearchHistory(
            search_type=search_type,
            search_query=search_query,
            result_count=result_count
        )
        session.add(history)
        await session.commit()


# ============ 对话相关操作 ============

async def create_conversation(title: str = "新对话") -> int:
    """创建新对话"""
    async with async_session_maker() as session:
        conv = Conversation(title=title)
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


async def list_conversations(limit: int = 50) -> List[dict]:
    """获取对话列表"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        convs = result.scalars().all()
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat()
            }
            for c in convs
        ]


async def get_conversation(conv_id: int) -> dict:
    """获取单个对话"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat()
        }


async def update_conversation_title(conv_id: int, title: str) -> bool:
    """更新对话标题"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        conv.title = title
        conv.updated_at = datetime.utcnow()
        await session.commit()
        return True


async def delete_conversation(conv_id: int) -> bool:
    """删除对话"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        await session.delete(conv)
        await session.commit()
        return True




async def delete_all_conversations() -> dict:
    """Delete all chat conversations and their messages.

    Notes:
    - Only clears `conversations` + `messages` tables; does not touch papers/canvas/etc.
    - Current DB schema does not scope conversations by user, so this clears everything.
    """
    async with async_session_maker() as session:
        conv_result = await session.execute(select(func.count(Conversation.id)))
        msg_result = await session.execute(select(func.count(Message.id)))
        conv_count = int(conv_result.scalar() or 0)
        msg_count = int(msg_result.scalar() or 0)

        # Delete children first to avoid FK issues if SQLite foreign keys are enabled.
        await session.execute(delete(Message))
        await session.execute(delete(Conversation))
        await session.commit()

        return {"conversations": conv_count, "messages": msg_count}
async def add_message(conv_id: int, role: str, content: str,
                      tool_calls: str = None, tool_call_id: str = None) -> int:
    """添加消息"""
    async with async_session_maker() as session:
        # 更新对话的更新时间
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            conv.updated_at = datetime.utcnow()

        msg = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg.id


async def get_messages(conv_id: int) -> List[dict]:
    """获取对话的所有消息"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
        )
        msgs = result.scalars().all()
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tool_calls": json.loads(m.tool_calls) if m.tool_calls else None,
                "tool_call_id": m.tool_call_id,
                "created_at": m.created_at.isoformat()
            }
            for m in msgs
        ]


async def fork_conversation(
    parent_conv_id: int,
    until_message_id: int,
    title: str = None,
) -> dict:
    """
    Fork a conversation by copying messages from a parent conversation up to a given message ID (inclusive).

    Returns:
        dict: {id, title, parent_conversation_id, forked_from_message_id, copied_message_count, copied_visible_message_count}
    """
    def _as_int(value: object, default: int) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except Exception:
            return default

    parent_conv_id = _as_int(parent_conv_id, 0)
    until_message_id = _as_int(until_message_id, 0)
    if parent_conv_id <= 0 or until_message_id <= 0:
        raise ValueError("invalid_parent_or_message_id")

    async with async_session_maker() as session:
        parent_result = await session.execute(
            select(Conversation).where(
                Conversation.id == parent_conv_id,
            )
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise ValueError("conversation_not_found")

        msgs_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == parent_conv_id)
            .order_by(Message.created_at)
        )
        msgs = list(msgs_result.scalars().all())
        if not msgs:
            raise ValueError("conversation_empty")

        copied: List[Message] = []
        copied_visible_count = 0
        found = False
        for m in msgs:
            copied.append(m)
            if m.role != "tool":
                copied_visible_count += 1
            if m.id == until_message_id:
                found = True
                break
        if not found:
            raise ValueError("message_not_found")

        new_title = (title or "").strip() or f"{parent.title} - 分支"
        conv = Conversation(title=new_title)
        session.add(conv)
        await session.flush()

        for m in copied:
            session.add(
                Message(
                    conversation_id=conv.id,
                    role=m.role,
                    content=m.content,
                    tool_calls=m.tool_calls,
                    tool_call_id=m.tool_call_id,
                )
            )

        conv.updated_at = datetime.utcnow()
        await session.commit()

        return {
            "id": conv.id,
            "title": conv.title,
            "parent_conversation_id": parent_conv_id,
            "forked_from_message_id": until_message_id,
            "copied_message_count": len(copied),
            "copied_visible_message_count": copied_visible_count,
        }


async def create_canvas_board(title: str = "", subject: str = "", snapshot: str = "") -> dict:
    """Create a new learning canvas board."""
    title = (title or "").strip() or "新画布"
    subject = (subject or "").strip()
    snapshot = snapshot or ""

    async with async_session_maker() as session:
        board = CanvasBoard(title=title, subject=subject, snapshot=snapshot, revision=1)
        session.add(board)
        await session.commit()
        await session.refresh(board)
        return {
            "id": board.id,
            "title": board.title,
            "subject": board.subject,
            "revision": board.revision,
            "created_at": board.created_at.isoformat(),
            "updated_at": board.updated_at.isoformat() if board.updated_at else board.created_at.isoformat(),
        }


async def list_canvas_boards(limit: int = 50, query: str = "") -> List[dict]:
    """List canvas boards (most recently updated first)."""
    limit = max(1, min(int(limit or 50), 200))
    query = (query or "").strip()

    async with async_session_maker() as session:
        stmt = select(CanvasBoard).order_by(desc(CanvasBoard.updated_at)).limit(limit)
        if query:
            # Escape LIKE wildcards to prevent pattern injection
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(CanvasBoard.title.like(f"%{escaped}%"))
        result = await session.execute(stmt)
        boards = list(result.scalars().all())
        return [
            {
                "id": b.id,
                "title": b.title,
                "subject": b.subject,
                "revision": b.revision,
                "created_at": b.created_at.isoformat() if b.created_at else "",
                "updated_at": b.updated_at.isoformat() if b.updated_at else "",
            }
            for b in boards
        ]


async def get_canvas_board(board_id: int) -> Optional[dict]:
    """Get a single canvas board (including snapshot)."""
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return None
        return {
            "id": board.id,
            "title": board.title,
            "subject": board.subject,
            "revision": board.revision,
            "snapshot": board.snapshot or "",
            "created_at": board.created_at.isoformat() if board.created_at else "",
            "updated_at": board.updated_at.isoformat() if board.updated_at else "",
        }


async def update_canvas_board(
    board_id: int,
    *,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    snapshot: Optional[str] = None,
    expected_revision: Optional[int] = None,
) -> dict:
    """
    Update a canvas board (optimistic concurrency via `expected_revision`).

    Returns:
        dict: {success, board?, conflict?, error?}
    """
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return {"success": False, "error": "board_not_found"}

        if expected_revision is not None and int(expected_revision) != int(board.revision or 0):
            return {
                "success": False,
                "conflict": True,
                "error": "revision_conflict",
                "server_board": {
                    "id": board.id,
                    "title": board.title,
                    "subject": board.subject,
                    "revision": board.revision,
                    "snapshot": board.snapshot or "",
                    "updated_at": board.updated_at.isoformat() if board.updated_at else "",
                },
            }

        if title is not None:
            board.title = (title or "").strip() or "新画布"
        if subject is not None:
            board.subject = (subject or "").strip()
        if snapshot is not None:
            board.snapshot = snapshot or ""
            board.revision = int(board.revision or 0) + 1

        await session.commit()
        await session.refresh(board)

        return {
            "success": True,
            "board": {
                "id": board.id,
                "title": board.title,
                "subject": board.subject,
                "revision": board.revision,
                "snapshot": board.snapshot or "",
                "updated_at": board.updated_at.isoformat() if board.updated_at else "",
            },
        }


async def create_canvas_board_version(board_id: int) -> dict:
    """Create an immutable version snapshot for a board."""
    async with async_session_maker() as session:
        result = await session.execute(select(CanvasBoard).where(CanvasBoard.id == int(board_id)))
        board = result.scalar_one_or_none()
        if not board:
            return {"success": False, "error": "board_not_found"}

        version = CanvasBoardVersion(board_id=board.id, revision=board.revision, snapshot=board.snapshot or "")
        session.add(version)
        await session.commit()
        await session.refresh(version)

        latest_result = await session.execute(
            select(CanvasBoardVersion)
            .where(CanvasBoardVersion.board_id == int(board_id))
            .order_by(desc(CanvasBoardVersion.created_at))
            .limit(30)
        )
        versions = list(latest_result.scalars().all())

        return {
            "success": True,
            "version": {
                "id": version.id,
                "board_id": version.board_id,
                "revision": version.revision,
                "created_at": version.created_at.isoformat() if version.created_at else "",
            },
            "versions": [
                {
                    "id": v.id,
                    "board_id": v.board_id,
                    "revision": v.revision,
                    "created_at": v.created_at.isoformat() if v.created_at else "",
                }
                for v in versions
            ],
        }


async def list_canvas_board_versions(board_id: int, limit: int = 30) -> List[dict]:
    """List recent version snapshots for a board."""
    limit = max(1, min(int(limit or 30), 200))
    async with async_session_maker() as session:
        result = await session.execute(
            select(CanvasBoardVersion)
            .where(CanvasBoardVersion.board_id == int(board_id))
            .order_by(desc(CanvasBoardVersion.created_at))
            .limit(limit)
        )
        versions = list(result.scalars().all())
        return [
            {
                "id": v.id,
                "board_id": v.board_id,
                "revision": v.revision,
                "created_at": v.created_at.isoformat() if v.created_at else "",
            }
            for v in versions
        ]


async def get_canvas_board_version(board_id: int, version_id: int) -> Optional[dict]:
    """Get a specific version snapshot (including snapshot payload)."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(CanvasBoardVersion).where(
                CanvasBoardVersion.board_id == int(board_id),
                CanvasBoardVersion.id == int(version_id),
            )
        )
        v = result.scalar_one_or_none()
        if not v:
            return None
        return {
            "id": v.id,
            "board_id": v.board_id,
            "revision": v.revision,
            "snapshot": v.snapshot or "",
            "created_at": v.created_at.isoformat() if v.created_at else "",
        }


# SQLite schema migration (best-effort for existing DBs)
def _sync_migrate_db_schema(conn) -> None:
    """Best-effort SQLite schema migrations for existing installations."""
    # paper_questions: allow local stem storage (no answers/analysis).
    try:
        pq_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(paper_questions)").fetchall()]
    except Exception:
        pq_cols = []

    def _add_col(table: str, name: str, ddl: str) -> None:
        if name in pq_cols:
            return
        try:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        except Exception:
            return

    if pq_cols:
        _add_col("paper_questions", "stem", "TEXT")
        _add_col("paper_questions", "stem_fingerprint", "VARCHAR(32)")
        _add_col("paper_questions", "difficulty_value", "FLOAT")
        _add_col("paper_questions", "quality_score", "INTEGER")
        _add_col("paper_questions", "quality_flags", "TEXT")
        _add_col("paper_questions", "knowledge_points_json", "TEXT")
        _add_col("paper_questions", "source", "VARCHAR(200)")
        _add_col("paper_questions", "date", "VARCHAR(50)")


async def list_blueprints(*, user_id: str, limit: int = 100) -> List[dict]:
    uid = (user_id or "").strip()
    if not uid:
        uid = "anonymous"

    async with async_session_maker() as session:
        result = await session.execute(
            select(Blueprint)
            .where(Blueprint.user_id == uid)
            .order_by(Blueprint.updated_at.desc())
            .limit(int(limit or 100))
        )
        items = result.scalars().all()

        out: List[dict] = []
        for bp in items:
            try:
                slots = json.loads(bp.slots_json or "[]")
                if not isinstance(slots, list):
                    slots = []
            except Exception:
                slots = []
            out.append(
                {
                    "id": bp.id,
                    "name": bp.name,
                    "subject": bp.subject,
                    "topic": bp.topic,
                    "slots": slots,
                    "createdAt": bp.created_at.isoformat() if bp.created_at else "",
                    "updatedAt": bp.updated_at.isoformat() if bp.updated_at else "",
                }
            )
        return out


async def get_blueprint(*, user_id: str, blueprint_id: str) -> Optional[dict]:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip()
    if not bid:
        return None

    async with async_session_maker() as session:
        result = await session.execute(
            select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid)
        )
        bp = result.scalar_one_or_none()
        if not bp:
            return None

        try:
            slots = json.loads(bp.slots_json or "[]")
            if not isinstance(slots, list):
                slots = []
        except Exception:
            slots = []

        return {
            "id": bp.id,
            "name": bp.name,
            "subject": bp.subject,
            "topic": bp.topic,
            "slots": slots,
            "createdAt": bp.created_at.isoformat() if bp.created_at else "",
            "updatedAt": bp.updated_at.isoformat() if bp.updated_at else "",
        }


async def save_blueprint(
    *,
    user_id: str,
    blueprint_id: str,
    name: str,
    subject: str,
    topic: str,
    slots: List[dict],
) -> dict:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip()
    if not bid:
        bid = uuid.uuid4().hex
    name = (name or "").strip()
    subject = (subject or "").strip()
    topic = (topic or "").strip()

    try:
        slots_json = json.dumps(slots or [], ensure_ascii=False)
    except Exception:
        slots_json = "[]"

    async with async_session_maker() as session:
        existing = None
        if bid:
            res = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
            existing = res.scalar_one_or_none()

        if existing:
            existing.name = name or existing.name
            existing.subject = subject or existing.subject
            existing.topic = topic
            existing.slots_json = slots_json
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return await get_blueprint(user_id=uid, blueprint_id=existing.id)  # type: ignore[return-value]

        bp = Blueprint(
            id=bid,
            user_id=uid,
            name=name,
            subject=subject,
            topic=topic,
            slots_json=slots_json,
        )
        session.add(bp)
        await session.commit()
        await session.refresh(bp)
        return await get_blueprint(user_id=uid, blueprint_id=bp.id)  # type: ignore[return-value]


async def delete_blueprint(*, user_id: str, blueprint_id: str) -> bool:
    uid = (user_id or "").strip() or "anonymous"
    bid = (blueprint_id or "").strip()
    if not bid:
        return False

    async with async_session_maker() as session:
        result = await session.execute(select(Blueprint).where(Blueprint.id == bid, Blueprint.user_id == uid))
        bp = result.scalar_one_or_none()
        if not bp:
            return False
        await session.delete(bp)
        await session.commit()
        return True


if __name__ == "__main__":
    import asyncio

    async def main():
        await init_db()
        print("数据库表创建成功！")

    asyncio.run(main())
