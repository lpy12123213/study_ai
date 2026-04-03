"""Agent tool implementations (split from `backend.agent.executor`).

The module layout is domain-grouped under:
- `backend.agent.tools.search`
- `backend.agent.tools.generation`
- `backend.agent.tools.analysis`
- `backend.agent.tools.knowledge`
- `backend.agent.tools.utils`

Back-compat:
Historically tools lived directly under `backend.agent.tools.<name>`. We alias those legacy module
paths to the new locations to avoid breaking existing imports and tests that patch by import path.
"""

from __future__ import annotations

import importlib
import sys
from typing import Dict

_LEGACY_MODULE_ALIASES: Dict[str, str] = {
    # utils
    "aggregation": "backend.agent.tools.utils.aggregation",
    "text_utils": "backend.agent.tools.utils.text_utils",
    # search
    "browse_web_pages": "backend.agent.tools.search.browse_web_pages",
    "deep_research": "backend.agent.tools.search.deep_research",
    "github_search": "backend.agent.tools.search.github_search",
    "mediawiki_search": "backend.agent.tools.search.mediawiki_search",
    "stackexchange_search": "backend.agent.tools.search.stackexchange_search",
    "web_search_knowledge": "backend.agent.tools.search.web_search_knowledge",
    "wikipedia_search": "backend.agent.tools.search.wikipedia_search",
    # generation
    "diagrams": "backend.agent.tools.generation.diagrams",
    "diagram_planning": "backend.agent.tools.generation.diagram_planning",
    "exports": "backend.agent.tools.generation.exports",
    "latex_export": "backend.agent.tools.generation.latex_export",
    "plots": "backend.agent.tools.generation.plots",
    # analysis
    "content_review": "backend.agent.tools.analysis.content_review",
    "refine_draft": "backend.agent.tools.analysis.refine_draft",
    "self_critique": "backend.agent.tools.analysis.self_critique",
    "source_synthesis": "backend.agent.tools.analysis.source_synthesis",
    # knowledge
    "knowledge_points": "backend.agent.tools.knowledge.knowledge_points",
    "knowledge_type_detection": "backend.agent.tools.knowledge.knowledge_type_detection",
    "question_bank": "backend.agent.tools.knowledge.question_bank",
    "study_archive": "backend.agent.tools.knowledge.study_archive",
    "study_material_generation": "backend.agent.tools.knowledge.study_material_generation",
}

for legacy_name, target in _LEGACY_MODULE_ALIASES.items():
    try:
        module = importlib.import_module(target)
    except Exception:
        continue
    sys.modules.setdefault(f"{__name__}.{legacy_name}", module)
    globals()[legacy_name] = module

__all__ = [
    "analysis",
    "generation",
    "knowledge",
    "search",
    "utils",
    *_LEGACY_MODULE_ALIASES.keys(),
]
