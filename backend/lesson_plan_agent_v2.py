"""Compatibility wrapper for the lesson plan agent (v2).

The original implementation was a single large file. It has been split into
`backend/lesson_plan_v2/*` modules.
"""

from __future__ import annotations

from backend.lesson_plan_v2.service import generate_lesson_plan_stream

__all__ = ["generate_lesson_plan_stream"]
