from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import (
    EssayEvaluation,
    ExamResult,
    ExamSession,
    LearningPlan,
    LearningPlanItem,
    StudentAnswer,
    WrongQuestion,
)

MASTERY_BUCKETS = (
    ("0-25", "0-25", 0, 25),
    ("26-50", "26-50", 26, 50),
    ("51-75", "51-75", 51, 75),
    ("76-100", "76-100", 76, 100),
)


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _dt(value: Any) -> Optional[datetime]:
    return value if isinstance(value, datetime) else None


def _date_key(value: datetime) -> str:
    return value.date().isoformat()


def _ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _avg(values: Iterable[float]) -> float:
    nums = [float(v) for v in values]
    if not nums:
        return 0.0
    return round(sum(nums) / len(nums), 4)


def _score_ratio(score: Any, max_score: Any) -> float:
    try:
        total = float(score or 0.0)
        max_value = float(max_score or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return _ratio(total, max_value)


def _empty_exam_insights() -> dict:
    return {
        "total_sessions": 0,
        "avg_score_ratio": 0.0,
        "trend": [],
        "objective": {"correct": 0, "total": 0, "ratio": 0.0},
        "subjective": {"score": 0.0, "max_score": 0.0, "ratio": 0.0},
        "accuracy_by_type": [],
        "recent": [],
    }


def _empty_essay_insights() -> dict:
    return {
        "total": 0,
        "avg_score_ratio": 0.0,
        "trend": [],
        "by_type": [],
    }


def _empty_wrongbook_insights() -> dict:
    return {
        "total": 0,
        "mastery_distribution": [
            {"bucket": bucket, "label": label, "count": 0} for bucket, label, _start, _end in MASTERY_BUCKETS
        ],
        "weak_points": [],
    }


def _empty_activity_insights() -> dict:
    return {
        "active_days": 0,
        "current_streak": 0,
        "plan_completion": {"completed": 0, "total": 0, "overdue": 0, "ratio": 0.0},
    }


def _trend_from_ratios(day_ratios: dict[str, list[float]], value_key: str = "score_ratio") -> list[dict]:
    return [
        {"date": day, value_key: _avg(values), "count": len(values)}
        for day, values in sorted(day_ratios.items(), key=lambda item: item[0])
    ]


async def exam_insights(session: AsyncSession, user_id: str, dt_from: datetime, dt_to: datetime) -> dict:
    uid = _require_user_id(user_id)
    start = _to_naive_utc(dt_from)
    end = _to_naive_utc(dt_to)

    result_stmt = (
        select(ExamResult, ExamSession)
        .join(ExamSession, ExamSession.id == ExamResult.session_id)
        .where(
            ExamResult.user_id == uid,
            ExamSession.user_id == uid,
            ExamSession.status == "submitted",
            ExamSession.submitted_at.is_not(None),
            ExamSession.submitted_at >= start,
            ExamSession.submitted_at <= end,
        )
        .order_by(ExamSession.submitted_at.desc())
    )
    result_rows = (await session.execute(result_stmt)).all()

    answer_stmt = (
        select(StudentAnswer)
        .join(ExamSession, ExamSession.id == StudentAnswer.session_id)
        .where(
            StudentAnswer.user_id == uid,
            ExamSession.user_id == uid,
            ExamSession.status == "submitted",
            ExamSession.submitted_at.is_not(None),
            ExamSession.submitted_at >= start,
            ExamSession.submitted_at <= end,
        )
    )
    answers = (await session.execute(answer_stmt)).scalars().all()

    out = _empty_exam_insights()
    if not result_rows and not answers:
        return out

    trend: dict[str, list[float]] = defaultdict(list)
    score_ratios: list[float] = []
    objective_correct = 0
    objective_total = 0
    subjective_score = 0.0
    subjective_max = 0.0
    recent: list[dict] = []

    for result, exam in result_rows:
        submitted_at = _dt(exam.submitted_at) or _dt(result.created_at)
        ratio = float(result.score_ratio or 0.0)
        score_ratios.append(ratio)
        if submitted_at:
            trend[_date_key(submitted_at)].append(ratio)
        objective_correct += int(result.objective_correct or 0)
        objective_total += int(result.objective_total or 0)
        subjective_score += float(result.subjective_score or 0.0)
        subjective_max += float(result.subjective_max or 0.0)
        if len(recent) < 5:
            recent.append(
                {
                    "session_id": str(exam.id or ""),
                    "paper_name": str(exam.paper_name or ""),
                    "score_ratio": ratio,
                    "submitted_at": submitted_at.isoformat() if submitted_at else None,
                }
            )

    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    for answer in answers:
        if answer.is_correct is None:
            continue
        qtype = str(answer.question_type or "").strip() or "unknown"
        by_type[qtype]["total"] += 1
        if int(answer.is_correct or 0):
            by_type[qtype]["correct"] += 1

    accuracy = [
        {
            "question_type": question_type,
            "correct": row["correct"],
            "total": row["total"],
            "ratio": _ratio(row["correct"], row["total"]),
        }
        for question_type, row in sorted(by_type.items(), key=lambda item: (-item[1]["total"], item[0]))
    ]

    out.update(
        {
            "total_sessions": len(result_rows),
            "avg_score_ratio": _avg(score_ratios),
            "trend": _trend_from_ratios(trend),
            "objective": {
                "correct": objective_correct,
                "total": objective_total,
                "ratio": _ratio(objective_correct, objective_total),
            },
            "subjective": {
                "score": round(subjective_score, 4),
                "max_score": round(subjective_max, 4),
                "ratio": _ratio(subjective_score, subjective_max),
            },
            "accuracy_by_type": accuracy,
            "recent": recent,
        }
    )
    return out


async def essay_insights(
    session: AsyncSession,
    user_id: str,
    dt_from: datetime,
    dt_to: datetime,
    subject: Optional[str] = None,
) -> dict:
    uid = _require_user_id(user_id)
    start = _to_naive_utc(dt_from)
    end = _to_naive_utc(dt_to)
    filters = [
        EssayEvaluation.user_id == uid,
        EssayEvaluation.created_at >= start,
        EssayEvaluation.created_at <= end,
    ]
    if subject:
        filters.append(EssayEvaluation.subject == str(subject).strip())
    rows = (
        (await session.execute(select(EssayEvaluation).where(and_(*filters)).order_by(EssayEvaluation.created_at.asc())))
        .scalars()
        .all()
    )

    out = _empty_essay_insights()
    if not rows:
        return out

    trend: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, list[float]] = defaultdict(list)
    ratios: list[float] = []
    for row in rows:
        ratio = _score_ratio(row.score_total, row.score_max)
        ratios.append(ratio)
        created_at = _dt(row.created_at)
        if created_at:
            trend[_date_key(created_at)].append(ratio)
        essay_type = str(row.essay_type or "").strip() or "unknown"
        by_type[essay_type].append(ratio)

    out.update(
        {
            "total": len(rows),
            "avg_score_ratio": _avg(ratios),
            "trend": _trend_from_ratios(trend),
            "by_type": [
                {"essay_type": key, "score_ratio": _avg(values), "count": len(values)}
                for key, values in sorted(by_type.items(), key=lambda item: (-len(item[1]), item[0]))
            ],
        }
    )
    return out


async def wrongbook_insights(
    session: AsyncSession,
    user_id: str,
    dt_from: datetime,
    dt_to: datetime,
    subject: Optional[str] = None,
) -> dict:
    uid = _require_user_id(user_id)
    start = _to_naive_utc(dt_from)
    end = _to_naive_utc(dt_to)
    filters = [
        WrongQuestion.user_id == uid,
        WrongQuestion.updated_at >= start,
        WrongQuestion.updated_at <= end,
    ]
    if subject:
        filters.append(WrongQuestion.subject == str(subject).strip())
    rows = (await session.execute(select(WrongQuestion).where(and_(*filters)))).scalars().all()

    out = _empty_wrongbook_insights()
    if not rows:
        return out

    bucket_counts = {bucket: 0 for bucket, _label, _start, _end in MASTERY_BUCKETS}
    weak: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        mastery = max(0, min(100, int(row.mastery or 0)))
        for bucket, _label, start_value, end_value in MASTERY_BUCKETS:
            if start_value <= mastery <= end_value:
                bucket_counts[bucket] += 1
                break
        kp = str(row.knowledge_point or "").strip() or "未标注"
        weak[kp].append(mastery)

    weak_points = [
        {"knowledge_point": key, "avg_mastery": round(sum(values) / len(values), 1), "count": len(values)}
        for key, values in weak.items()
    ]
    weak_points.sort(key=lambda item: (item["avg_mastery"], -item["count"], item["knowledge_point"]))

    out.update(
        {
            "total": len(rows),
            "mastery_distribution": [
                {"bucket": bucket, "label": label, "count": bucket_counts[bucket]}
                for bucket, label, _start, _end in MASTERY_BUCKETS
            ],
            "weak_points": weak_points[:10],
        }
    )
    return out


async def activity_insights(session: AsyncSession, user_id: str, dt_from: datetime, dt_to: datetime) -> dict:
    uid = _require_user_id(user_id)
    start = _to_naive_utc(dt_from)
    end = _to_naive_utc(dt_to)
    active_dates: set[str] = set()

    exam_dates = (
        (
            await session.execute(
                select(ExamSession.submitted_at).where(
                    ExamSession.user_id == uid,
                    ExamSession.status == "submitted",
                    ExamSession.submitted_at.is_not(None),
                    ExamSession.submitted_at >= start,
                    ExamSession.submitted_at <= end,
                )
            )
        )
        .scalars()
        .all()
    )
    essay_dates = (
        (
            await session.execute(
                select(EssayEvaluation.created_at).where(
                    EssayEvaluation.user_id == uid,
                    EssayEvaluation.created_at >= start,
                    EssayEvaluation.created_at <= end,
                )
            )
        )
        .scalars()
        .all()
    )
    plan_completed_dates = (
        (
            await session.execute(
                select(LearningPlanItem.completed_at)
                .join(LearningPlan, LearningPlan.id == LearningPlanItem.plan_id)
                .where(
                    LearningPlan.user_id == uid,
                    LearningPlanItem.completed == 1,
                    LearningPlanItem.completed_at.is_not(None),
                    LearningPlanItem.completed_at >= start,
                    LearningPlanItem.completed_at <= end,
                )
            )
        )
        .scalars()
        .all()
    )

    for value in [*exam_dates, *essay_dates, *plan_completed_dates]:
        if isinstance(value, datetime):
            active_dates.add(_date_key(value))

    plan_rows = (
        (
            await session.execute(
                select(LearningPlanItem)
                .join(LearningPlan, LearningPlan.id == LearningPlanItem.plan_id)
                .where(LearningPlan.user_id == uid, LearningPlan.archived == 0)
            )
        )
        .scalars()
        .all()
    )
    completed = sum(1 for item in plan_rows if int(item.completed or 0) == 1)
    overdue = sum(
        1
        for item in plan_rows
        if int(item.completed or 0) != 1 and isinstance(item.due_at, datetime) and item.due_at <= end
    )

    current_streak = 0
    cursor = end.date()
    while cursor.isoformat() in active_dates:
        current_streak += 1
        cursor = cursor.fromordinal(cursor.toordinal() - 1)

    return {
        "active_days": len(active_dates),
        "current_streak": current_streak,
        "plan_completion": {
            "completed": completed,
            "total": len(plan_rows),
            "overdue": overdue,
            "ratio": _ratio(completed, len(plan_rows)),
        },
    }


async def get_insights_overview(
    session: AsyncSession,
    *,
    user_id: str,
    dt_from: datetime,
    dt_to: datetime,
    subject: Optional[str] = None,
) -> dict:
    uid = _require_user_id(user_id)
    normalized_subject = str(subject or "").strip() or None
    return {
        "exams": await exam_insights(session, uid, dt_from, dt_to),
        "essays": await essay_insights(session, uid, dt_from, dt_to, subject=normalized_subject),
        "wrongbook": await wrongbook_insights(session, uid, dt_from, dt_to, subject=normalized_subject),
        "activity": await activity_insights(session, uid, dt_from, dt_to),
    }
