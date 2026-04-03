"""Database repositories (CRUD helpers).

These modules keep DB operations grouped by domain to keep each file small and
maintainable.
"""

from __future__ import annotations

import importlib
import sys
from typing import Dict

# Domain-grouped subpackages:
# - backend.database.repositories.question
# - backend.database.repositories.content
# - backend.database.repositories.system
#
# Back-compat:
# Many call sites historically import `backend.database.repositories.<module>` directly.
# After regrouping, we keep those imports working by aliasing legacy module names into
# `sys.modules` at package import time.

_LEGACY_MODULE_ALIASES: Dict[str, str] = {
    # question domain
    "question_library": "backend.database.repositories.question.question_library",
    "question_cache": "backend.database.repositories.question.question_cache",
    "papers": "backend.database.repositories.question.papers",
    "blueprints": "backend.database.repositories.question.blueprints",
    # content domain
    "conversations": "backend.database.repositories.content.conversations",
    "study_archives": "backend.database.repositories.content.study_archives",
    "templates": "backend.database.repositories.content.templates",
    "annotations": "backend.database.repositories.content.annotations",
    "wrongbook": "backend.database.repositories.content.wrongbook",
    # system domain
    "tasks": "backend.database.repositories.system.tasks",
    "user_settings": "backend.database.repositories.system.user_settings",
    "feedback": "backend.database.repositories.system.feedback",
    "search": "backend.database.repositories.system.search",
    "search_history": "backend.database.repositories.system.search_history",
    "generated_files": "backend.database.repositories.system.generated_files",
    "formula_cache": "backend.database.repositories.system.formula_cache",
    "share_links": "backend.database.repositories.system.share_links",
    "item_meta": "backend.database.repositories.system.item_meta",
    "canvas": "backend.database.repositories.system.canvas",
    "learning_plans": "backend.database.repositories.system.learning_plans",
}

for legacy_name, target in _LEGACY_MODULE_ALIASES.items():
    try:
        module = importlib.import_module(target)
    except Exception:
        # Keep package import resilient (some envs may not have DB deps ready).
        continue
    sys.modules.setdefault(f"{__name__}.{legacy_name}", module)
    globals()[legacy_name] = module

__all__ = [
    "question",
    "content",
    "system",
    *_LEGACY_MODULE_ALIASES.keys(),
]
