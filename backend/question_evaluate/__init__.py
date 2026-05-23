"""Question evaluation domain services.

Migration note (see ``docs/MIGRATION_PLAN.md``): the canonical location is now
``backend.generation.question_evaluate``. This package keeps old submodule
imports working for one release cycle.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "generation" / "question_evaluate"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]
