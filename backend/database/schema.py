from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database.base import Base


def _utcnow() -> datetime:
    """Return a naive UTC datetime for legacy SQLite schemas.

    Python 3.12+ deprecates `datetime.utcnow()`. We keep legacy naive storage
    while using timezone-aware UTC as the source of truth.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Paper(Base):
    """试卷表"""

    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    paper_name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    questions = relationship("PaperQuestion", back_populates="paper", cascade="all, delete-orphan")


class PaperQuestion(Base):
    """试卷题目关联表（保存题目编号 + 本地题干/解析缓存）。"""

    __tablename__ = "paper_questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
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

    __table_args__ = (
        Index("ix_paper_questions_user_paper_order", "user_id", "paper_id", "question_order"),
        Index("ix_paper_questions_user_question", "user_id", "question_id"),
    )


class ExamSession(Base):
    """Student paper-taking session."""

    __tablename__ = "exam_sessions"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False, index=True)
    paper_name = Column(String(200), nullable=False, default="")
    mode = Column(String(20), nullable=False, default="untimed", index=True)
    time_limit_minutes = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=_utcnow, index=True)
    submitted_at = Column(DateTime, nullable=True, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    status = Column(String(20), nullable=False, default="in_progress", index=True)
    total_score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    answers = relationship("StudentAnswer", back_populates="session", cascade="all, delete-orphan")
    result = relationship("ExamResult", back_populates="session", cascade="all, delete-orphan", uselist=False)

    __table_args__ = (
        Index("ix_exam_sessions_user_status", "user_id", "status"),
        Index("ix_exam_sessions_user_paper", "user_id", "paper_id"),
    )


class StudentAnswer(Base):
    """Autosaved student answer for one question in an exam session."""

    __tablename__ = "student_answers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), ForeignKey("exam_sessions.id"), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    question_id = Column(String(100), nullable=False, index=True)
    question_type = Column(String(50), nullable=False, default="")
    question_order = Column(Integer, default=0)

    selected_options_json = Column(Text, default="[]")
    fill_blank_text = Column(Text, default="")
    handwriting_image_path = Column(String(500), default="")
    text_answer = Column(Text, default="")

    is_correct = Column(Integer, nullable=True)
    score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    grading_json = Column(Text, default="{}")
    auto_saved_at = Column(DateTime, default=_utcnow, index=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    session = relationship("ExamSession", back_populates="answers")

    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_student_answers_session_question"),
        Index("ix_student_answers_user_session", "user_id", "session_id"),
    )


class ExamResult(Base):
    """Final score summary for a submitted exam session."""

    __tablename__ = "exam_results"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), ForeignKey("exam_sessions.id"), nullable=False, unique=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    total_score = Column(Float, default=0.0)
    max_score = Column(Float, default=0.0)
    score_ratio = Column(Float, default=0.0)
    objective_correct = Column(Integer, default=0)
    objective_total = Column(Integer, default=0)
    subjective_score = Column(Float, default=0.0)
    subjective_max = Column(Float, default=0.0)
    breakdown_json = Column(Text, default="[]")
    ai_feedback_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    session = relationship("ExamSession", back_populates="result")

    __table_args__ = (
        Index("ix_exam_results_user_session", "user_id", "session_id"),
    )


class Blueprint(Base):
    """组卷蓝图（教师侧配置）。"""

    __tablename__ = "blueprints"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    name = Column(String(200), nullable=False, default="")
    subject = Column(String(100), nullable=False, default="")
    topic = Column(String(200), nullable=False, default="")
    slots_json = Column(Text, nullable=False, default="[]")  # JSON: BlueprintSlot[]
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class SearchHistory(Base):
    """搜索历史记录"""

    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    search_type = Column(String(50))
    search_query = Column(String(500))
    result_count = Column(Integer)
    created_at = Column(DateTime, default=_utcnow)


class Conversation(Base):
    """对话会话表"""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(Base):
    """消息表"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user' | 'assistant' | 'tool'
    content = Column(Text)
    tool_calls = Column(Text)  # JSON: 工具调用信息
    tool_call_id = Column(String(100))  # 工具调用ID（用于 tool 角色）
    created_at = Column(DateTime, default=_utcnow)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )


class CanvasBoard(Base):
    """学习画布（tldraw store snapshot 持久化）。"""

    __tablename__ = "canvas_boards"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    title = Column(String(200), nullable=False, default="新画布")
    subject = Column(String(100), default="")
    revision = Column(Integer, default=1)
    snapshot = Column(Text, default="")  # JSON serialized store snapshot
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    versions = relationship("CanvasBoardVersion", back_populates="board", cascade="all, delete-orphan")


class CanvasBoardVersion(Base):
    """画布版本历史（增量备份）。"""

    __tablename__ = "canvas_board_versions"

    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("canvas_boards.id"), nullable=False)
    revision = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)  # JSON serialized store snapshot
    created_at = Column(DateTime, default=_utcnow)

    board = relationship("CanvasBoard", back_populates="versions")


class UsedQuestion(Base):
    """全局去重集（跨重启），用于组卷避免重复题目。"""

    __tablename__ = "used_questions"

    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="")
    used_at = Column(DateTime, default=_utcnow)


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

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class FormulaLatexCache(Base):
    """Persistent cache for Zujuan formula hash -> LaTeX."""

    __tablename__ = "formula_latex_cache"

    formula_hash = Column(String(32), primary_key=True)
    latex = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class QuestionLibraryItem(Base):
    """用户维度的本地题库条目（来源/隐藏/评分等“题库语义”）。"""

    __tablename__ = "question_library"

    user_id = Column(String(64), primary_key=True)
    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="", index=True)
    origin = Column(String(20), default="crawled", index=True)  # crawled|ai

    hidden = Column(Integer, default=0, index=True)  # 0/1
    starred = Column(Integer, default=0, index=True)  # 0/1

    ai_score = Column(Integer)
    ai_verdict = Column(String(20), default="")
    ai_dimensions_json = Column(Text, default="")
    ai_summary = Column(Text, default="")

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_question_library_user_hidden_updated", "user_id", "hidden", "updated_at"),
        Index("ix_question_library_user_subject_hidden_updated", "user_id", "subject", "hidden", "updated_at"),
        Index("ix_question_library_user_origin_hidden_updated", "user_id", "origin", "hidden", "updated_at"),
        Index("ix_question_library_user_score_updated", "user_id", "ai_score", "updated_at"),
        Index(
            "ix_question_library_unscored_crawled",
            "user_id",
            "subject",
            "question_id",
            sqlite_where=(origin == "crawled") & ai_score.is_(None),
        ),
    )


class StudyArchive(Base):
    """自学材料归档（本地知识库，用于复用与加速）。"""

    __tablename__ = "study_archives"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, default="")
    subject = Column(String(100), default="")
    topic = Column(String(200), default="")
    # Deterministic fingerprint (user+subject+topic+requirements) used for cache lookup.
    # Versions of the same content share the same base_fingerprint while keeping a unique `fingerprint`.
    base_fingerprint = Column(String(32), index=True, default="")
    fingerprint = Column(String(32), index=True, unique=True, nullable=False)
    preset = Column(String(32), default="")
    requirements = Column(Text, default="")

    markdown = Column(Text, default="")
    sections_json = Column(Text, default="[]")

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_study_archives_user_updated", "user_id", "updated_at"),
        Index("ix_study_archives_user_base_fingerprint", "user_id", "base_fingerprint"),
        Index("ix_study_archives_user_base_fingerprint_created", "user_id", "base_fingerprint", "created_at"),
    )


class UsedQuestionUser(Base):
    """用户维度的去重集（用于组卷避免重复题目）。"""

    __tablename__ = "used_questions_user"

    user_id = Column(String(64), primary_key=True)
    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="")
    used_at = Column(DateTime, default=_utcnow)


class GeneratedFile(Base):
    """Metadata for locally generated files served from `.local/media/generated/`."""

    __tablename__ = "generated_files"

    filename = Column(String(200), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    file_type = Column(String(32), default="", index=True)  # md|tex|pdf|image|zip|...
    mime_type = Column(String(100), default="")
    sha256 = Column(String(64), default="", index=True)
    bytes = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)


class Task(Base):
    """Unified persisted task record (cross-feature)."""

    __tablename__ = "tasks"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")

    task_type = Column(String(50), nullable=False, index=True, default="")
    title = Column(String(200), nullable=False, default="")
    status = Column(
        String(20), nullable=False, index=True, default="running"
    )  # running|paused|completed|failed|canceled
    progress = Column(Float, default=0.0)
    last_seq = Column(Integer, default=0)

    parent_task_id = Column(String(64), index=True)

    request_json = Column(Text, default="")
    result_json = Column(Text, default="")
    error_json = Column(Text, default="")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)
    started_at = Column(DateTime, nullable=True, index=True)
    ended_at = Column(DateTime, nullable=True, index=True)

    events = relationship("TaskEvent", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tasks_user_status_updated", "user_id", "status", "updated_at"),
        Index("ix_tasks_user_type_updated", "user_id", "task_type", "updated_at"),
        Index("ix_tasks_user_type_status_ended", "user_id", "task_type", "status", "ended_at"),
        Index("ix_tasks_user_updated", "user_id", "updated_at"),
    )


class TaskEvent(Base):
    """Streaming events for tasks (SSE replay)."""

    __tablename__ = "task_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), ForeignKey("tasks.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    event_type = Column(String(50), index=True, default="")
    payload_json = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow, index=True)

    task = relationship("Task", back_populates="events")

    __table_args__ = (UniqueConstraint("task_id", "seq", name="ux_task_events_task_id_seq"),)


class TaskDurationAggregate(Base):
    """Per-task-type duration summary for ETA inputs."""

    __tablename__ = "task_duration_aggregates"

    task_type = Column(String(50), primary_key=True)
    completed_count = Column(Integer, nullable=False, default=0)
    duration_sum_seconds = Column(Float, nullable=False, default=0.0)
    duration_ema_seconds = Column(Float, nullable=False, default=0.0)
    last_duration_seconds = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, index=False)

    __table_args__ = (Index("ix_task_duration_aggregates_updated_at", "updated_at"),)


class UserItemMeta(Base):
    """Generic per-user metadata for arbitrary items (star/pin/tags)."""

    __tablename__ = "user_item_meta"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    item_type = Column(String(32), nullable=False, index=True, default="")
    item_id = Column(String(64), nullable=False, index=True, default="")

    starred = Column(Integer, default=0, index=True)
    pinned = Column(Integer, default=0, index=True)
    tags_json = Column(Text, default="[]")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    __table_args__ = (UniqueConstraint("user_id", "item_type", "item_id", name="ux_user_item_meta"),)


class UserSettings(Base):
    """Cross-device synced user settings (JSON)."""

    __tablename__ = "user_settings"

    user_id = Column(String(64), primary_key=True)
    settings_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)


class ShareLink(Base):
    """Public read-only share tokens for selected items."""

    __tablename__ = "share_links"

    token = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    item_type = Column(String(32), nullable=False, index=True, default="")
    item_id = Column(String(64), nullable=False, index=True, default="")

    expires_at = Column(DateTime, nullable=True, index=True)
    password_hash = Column(String(200), default="")

    created_at = Column(DateTime, default=_utcnow, index=True)


class LearningPlan(Base):
    """Learning plan with todo items and optional reminders."""

    __tablename__ = "learning_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    title = Column(String(200), default="", index=True)
    archived = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    items = relationship("LearningPlanItem", back_populates="plan", cascade="all, delete-orphan")


class LearningPlanItem(Base):
    """Single item within a learning plan."""

    __tablename__ = "learning_plan_items"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("learning_plans.id"), nullable=False, index=True)
    title = Column(String(200), default="")
    description = Column(Text, default="")
    due_at = Column(DateTime, nullable=True, index=True)
    completed = Column(Integer, default=0, index=True)
    completed_at = Column(DateTime, nullable=True)
    sort_order = Column(Integer, default=0, index=True)
    source_ref_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    plan = relationship("LearningPlan", back_populates="items")


class Annotation(Base):
    """User annotations on a document/paragraph/question, with anchors for deep links."""

    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    item_type = Column(String(32), nullable=False, index=True, default="")
    item_id = Column(String(64), nullable=False, index=True, default="")
    anchor = Column(String(120), default="", index=True)
    snippet = Column(String(300), default="")
    content = Column(Text, default="")
    tags_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)


class FeedbackReport(Base):
    """User feedback report with captured context for maintainers."""

    __tablename__ = "feedback_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    title = Column(String(200), default="")
    description = Column(Text, default="")
    context_json = Column(Text, default="{}")
    status = Column(String(32), index=True, default="received")  # received|triaged|in_progress|done
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)


class UserTemplate(Base):
    """Reusable prompt/parameter templates."""

    __tablename__ = "user_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    template_type = Column(String(32), index=True, default="")  # study_materials|paper_compose|lesson_plan|...
    name = Column(String(200), default="", index=True)
    body_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)


class WrongQuestion(Base):
    """Per-user wrongbook entry (question ids + review metadata)."""

    __tablename__ = "wrong_questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    question_id = Column(String(50), nullable=False, index=True)
    subject = Column(String(100), default="", index=True)
    knowledge_point = Column(String(200), default="", index=True)
    mastery = Column(Integer, default=0, index=True)  # 0..100
    note = Column(Text, default="")
    tags_json = Column(Text, default="[]")
    source_ref_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    __table_args__ = (UniqueConstraint("user_id", "question_id", name="ux_wrong_questions_user_question"),)


class LessonPlanRecord(Base):
    """Persisted lesson plan (educator-authored, optionally AI-assisted).

    Replaces the legacy module-level dict in
    ``backend.generation.lesson_plan.store`` so plans survive restarts and
    multi-worker deployments.
    """

    __tablename__ = "lesson_plans"

    # ``id`` mirrors the public plan id used by the API (uuid4 hex). Stored as
    # ``String`` rather than autoincrement so existing JSON snapshots can be
    # migrated 1:1 without remapping.
    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    title = Column(String(255), nullable=False, default="")
    subject = Column(String(100), default="", index=True)
    grade = Column(String(50), default="")
    topic = Column(String(200), default="")
    duration_minutes = Column(Integer, default=45)
    status = Column(String(32), default="draft", index=True)
    objectives_json = Column(Text, default="[]")
    sections_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    __table_args__ = (
        Index("ix_lesson_plans_user_updated", "user_id", "updated_at"),
    )


class AuthUser(Base):
    """Persisted application user (login + JWT identity).

    Replaces the module-level ``_users`` dict + ``.local/users.json`` snapshot
    so credentials are consistent across uvicorn workers.
    """

    __tablename__ = "auth_users"

    user_id = Column(String(64), primary_key=True, index=True)
    username = Column(String(120), nullable=False, unique=True, index=True)
    password_hash = Column(String(200), nullable=False, default="")
    role = Column(String(32), nullable=False, default="user", index=True)
    token_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)


class RevokedJwt(Base):
    """JWT ``jti`` revocation list shared across workers.

    Entries with ``exp_ts`` in the past are pruned on read.
    """

    __tablename__ = "auth_revoked_jwt"

    jti = Column(String(64), primary_key=True)
    exp_ts = Column(Integer, nullable=False, default=0, index=True)
    revoked_at = Column(DateTime, default=_utcnow, index=True)



class EssayEvaluation(Base):
    """Persisted essay-evaluation history (one row per scored submission)."""

    __tablename__ = "essay_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), nullable=False, index=True, default="")
    subject = Column(String(40), default="语文", index=True)
    topic = Column(String(200), default="")
    essay_type = Column(String(32), default="argumentative", index=True)
    grade_band = Column(String(32), default="senior", index=True)
    language = Column(String(8), default="zh", index=True)

    essay_text = Column(Text, nullable=False, default="")
    requirements = Column(Text, default="")

    score_total = Column(Float, default=0.0, index=True)
    score_max = Column(Float, default=0.0)
    grade = Column(String(32), default="")

    scores_json = Column(Text, default="[]")          # List[EssayScore]
    feedback_json = Column(Text, default="{}")        # summary/strengths/weaknesses/suggestions/paragraph_feedback/rewrite
    model = Column(String(100), default="")

    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, index=True)

    __table_args__ = (
        Index("ix_essay_evaluations_user_created", "user_id", "created_at"),
    )
