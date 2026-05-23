"""Migration forwarder for ``backend.question_library``.

See ``docs/MIGRATION_PLAN.md``: the canonical location is now
``backend.generation.question_library``. This package keeps old submodule
imports working for one release cycle. New code should import from the
canonical path directly.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "generation" / "question_library"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]
