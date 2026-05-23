"""Study materials helpers (task manager, SSE replay, etc.).

Migration note (see ``docs/MIGRATION_PLAN.md``): the canonical location is now
``backend.generation.study_materials``. This package keeps old submodule
imports working for one release cycle.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "generation" / "study_materials"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]
