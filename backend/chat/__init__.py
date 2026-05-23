"""Migration forwarder for ``backend.chat``.

See ``docs/MIGRATION_PLAN.md``: the canonical location is now
``backend.workspace.chat``. This package keeps old submodule imports working
for one release cycle. New code should import from the canonical path directly.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parents[1] / "workspace" / "chat"
__path__ = [str(Path(__file__).resolve().parent), str(_CANONICAL_DIR)]

sys.modules.setdefault(f"{__name__}.service", importlib.import_module("backend.workspace.chat.service"))
