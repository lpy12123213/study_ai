from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database.base import Base


class Paper(Base):
    """试卷表"""

    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    paper_name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    questions = relationship("PaperQuestion", back_populates="paper", cascade="all, delete-orphan")


class PaperQuestion(Base):
    """试卷题目关联表（保存题目编号 + 本地题干/解析缓存）。"""

    __tablename__ = "paper_questions"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    question_id = Column(String(50), nullable=False)  # 题目编号
    question_order = Column(Integer)  # 题目顺序
    question_type = Column(String(50))  # 题型
    difficulty = Column(String(20))  # 难度
    knowledge_point = Column(String(200))  # 知识点
    source_url = Column(String(500))  # 题目来源URL

    # Optional local storage for the question stem/details.
    stem = Column(Text, default="")  # 题干纯文本（含 LaTeX 公式占位）
    stem_fingerprint = Column(String(32), default="")  # md5，用于去重/复用
    difficulty_value = Column(Float)  # 难度系数（越小越难）
    quality_score = Column(Integer, default=0)  # 0-100
    quality_flags = Column(Text, default="")  # JSON string list
    knowledge_points_json = Column(Text, default="")  # JSON string list
    source = Column(String(200), default="")  # 来源（如：xx年期末）
    date = Column(String(50), default="")  # 日期（如：2024/05）

    # Optional: answer/analysis (teacher-side local storage only).
    answer = Column(Text, default="")
    analysis = Column(Text, default="")

    paper = relationship("Paper", back_populates="questions")


class Blueprint(Base):
    """组卷蓝图（教师侧配置）。"""

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
    search_type = Column(String(50))
    search_query = Column(String(500))
    result_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """对话会话表"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """消息表"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'tool'
    content = Column(Text)
    tool_calls = Column(Text)  # JSON: 工具调用信息
    tool_call_id = Column(String(100))  # 工具调用ID（用于 tool 角色）
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class CanvasBoard(Base):
    """学习画布（tldraw store snapshot 持久化）。"""

    __tablename__ = "canvas_boards"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, default="新画布")
    subject = Column(String(100), default="")
    revision = Column(Integer, default=1)
    snapshot = Column(Text, default="")  # JSON serialized store snapshot
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship("CanvasBoardVersion", back_populates="board", cascade="all, delete-orphan")


class CanvasBoardVersion(Base):
    """画布版本历史（增量备份）。"""

    __tablename__ = "canvas_board_versions"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("canvas_boards.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON serialized store snapshot
    created_at = Column(DateTime, default=datetime.utcnow)

    board = relationship("CanvasBoard", back_populates="versions")


class UsedQuestion(Base):
    """全局去重集（跨重启），用于组卷避免重复题目。"""

    __tablename__ = "used_questions"

    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="")
    used_at = Column(DateTime, default=datetime.utcnow)


class QuestionCache(Base):
    """题目元数据缓存（按 question_id 复用，减少重复抓取）。"""

    __tablename__ = "question_cache"

    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="")
    question_type = Column(String(50), default="")
    difficulty = Column(String(20), default="")
    knowledge_point = Column(String(200), default="")
    source_url = Column(String(500), default="")

    stem = Column(Text, default="")
    stem_fingerprint = Column(String(32), default="")
    answer = Column(Text, default="")
    analysis = Column(Text, default="")

    difficulty_value = Column(Float)
    quality_score = Column(Integer, default=0)
    quality_flags = Column(Text, default="")
    knowledge_points_json = Column(Text, default="")
    source = Column(String(200), default="")
    date = Column(String(50), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StudyArchive(Base):
    """自学材料归档（本地知识库，用于复用与加速）。"""

    __tablename__ = "study_archives"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, default="")
    subject = Column(String(100), default="")
    topic = Column(String(200), default="")
    fingerprint = Column(String(32), index=True, unique=True, nullable=False)
    preset = Column(String(32), default="")
    requirements = Column(Text, default="")

    markdown = Column(Text, default="")
    sections_json = Column(Text, default="[]")

    created_at = Column(DateTime, default=datetime.utcnow)

