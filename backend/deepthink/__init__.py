"""DeepThink (Tree-of-Thoughts) package.

Migration note (see ``docs/MIGRATION_PLAN.md``): the canonical location is now
``backend.generation.deepthink``. This package keeps old submodule imports
working for one release cycle.

New code should import from ``backend.generation.deepthink.*`` directly.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "generation" / "deepthink"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]
