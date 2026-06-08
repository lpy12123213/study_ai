from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, TypedDict

Rating = Literal["again", "hard", "good", "easy"]

RATING_QUALITY: dict[Rating, int] = {"again": 2, "hard": 3, "good": 4, "easy": 5}
MASTERY_DELTA: dict[Rating, int] = {"again": -20, "hard": 5, "good": 15, "easy": 25}


class ReviewSchedule(TypedDict):
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review_at: datetime


def _quality_for_rating(rating: str) -> int:
    try:
        return RATING_QUALITY[rating]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError("invalid_review_rating") from exc


def clamp_mastery(value: int | float | str | None) -> int:
    try:
        raw = int(value if value is not None else 0)
    except (TypeError, ValueError):
        raw = 0
    return max(0, min(100, raw))


def apply_mastery_delta(mastery: int | float | str | None, rating: str) -> int:
    if rating not in MASTERY_DELTA:
        raise ValueError("invalid_review_rating")
    return clamp_mastery(clamp_mastery(mastery) + MASTERY_DELTA[rating])  # type: ignore[index]


def schedule_review(
    *,
    rating: str,
    ease_factor: float,
    interval_days: int,
    repetitions: int,
    now: datetime,
) -> ReviewSchedule:
    q = _quality_for_rating(rating)
    try:
        ease = float(ease_factor or 2.5)
    except (TypeError, ValueError):
        ease = 2.5
    try:
        interval = int(interval_days or 0)
    except (TypeError, ValueError):
        interval = 0
    try:
        reps = int(repetitions or 0)
    except (TypeError, ValueError):
        reps = 0

    ease = max(1.3, ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))

    if q < 3:
        next_reps = 0
        next_interval = 1
    else:
        next_reps = reps + 1
        if reps == 0:
            next_interval = 1
        elif reps == 1:
            next_interval = 6
        else:
            next_interval = max(1, int(round(max(1, interval) * ease)))

    return {
        "ease_factor": ease,
        "interval_days": next_interval,
        "repetitions": next_reps,
        "next_review_at": now + timedelta(days=next_interval),
    }
