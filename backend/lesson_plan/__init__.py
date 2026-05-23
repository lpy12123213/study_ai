"""Lesson plan generation domain.

Migration note (see ``docs/MIGRATION_PLAN.md``): the canonical location for
this module is now ``backend.generation.lesson_plan``. This package keeps old
submodule imports working for one release cycle.

New code should import from ``backend.generation.lesson_plan.*`` directly.
"""

from __future__ import annotations

from pathlib import Path

from backend.generation.lesson_plan.service import generate_lesson_plan_stream

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "generation" / "lesson_plan"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]

__all__ = ["generate_lesson_plan_stream"]
