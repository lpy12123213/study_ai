"""Migration forwarder for ``backend.crawler``.

See ``docs/MIGRATION_PLAN.md``: the canonical location is now
``backend.integrations.crawler``. This package keeps old submodule imports
working for one release cycle. New code should import from the canonical path
directly.
"""

from __future__ import annotations

from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "integrations" / "crawler"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]
